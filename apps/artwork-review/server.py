"""Loopback-only HTTP server; archive records and images are never written."""
from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import secrets
import socket
import sys
import threading
from urllib.parse import parse_qs, urlparse
import webbrowser

from core import Archive, Conflict, DECISIONS, DEFAULT_START, SCORES, markdown

APP_DIR = Path(__file__).resolve().parent
STATIC = APP_DIR / 'static'


def code_version():
    hasher = hashlib.sha256()
    for path in (APP_DIR / 'server.py', APP_DIR / 'core.py', STATIC / 'app.js', STATIC / 'style.css', STATIC / 'index.html'):
        hasher.update(path.read_bytes())
    return hasher.hexdigest()


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def server_bind(self):
        # Windows SO_REUSEADDR can let two servers bind and split traffic on one port.
        if os.name == 'nt':
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def __init__(self, archive, port=8931):
        self.archive = archive
        self.token = secrets.token_urlsafe(32)
        self.code_version = code_version()
        self.thumbnail_lock = threading.Lock()
        super().__init__(('127.0.0.1', port), Handler)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f'{self.log_date_time_string()} {fmt % args}', flush=True)

    def send(self, status, body, content_type='application/json; charset=utf-8', filename=None, cache=False):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        elif isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'private, max-age=3600' if cache else 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        if filename:
            self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def valid_host(self):
        host = self.headers.get('Host', '')
        port = self.server.server_port
        return host in (f'127.0.0.1:{port}', f'localhost:{port}')

    def do_GET(self):
        if not self.valid_host():
            self.send(403, {'error': '仅允许本机访问'})
            return
        try:
            self.get()
        except KeyError as exc:
            self.send(404, {'error': str(exc)})
        except (ValueError, TypeError) as exc:
            self.send(400, {'error': str(exc)})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            self.log_error('GET failed: %s', exc)
            self.send(500, {'error': '读取失败，请检查服务日志后重试'})

    def get(self):
        parsed = urlparse(self.path)
        route = parsed.path
        params = {k: v[-1] for k, v in parse_qs(parsed.query, keep_blank_values=True).items()}
        archive = self.server.archive
        if route == '/health':
            self.send(200, {'app': 'arco-artwork-review', 'root': str(archive.root), 'pid': os.getpid(), 'code_version': self.server.code_version})
        elif route == '/api/bootstrap':
            rows = archive.rows()
            self.send(200, {'token': self.server.token, 'scores': SCORES, 'decisions': DECISIONS,
                'default_start': DEFAULT_START, 'total_versions': len(rows), 'refreshed_at': archive.refreshed_at,
                'variants': dict(sorted({i['variant_id']: i['variant'] for i in rows}.items())),
                'statuses': sorted({i['status'] for i in rows}), 'session': archive.store.get_setting('session'),
                'problems': archive.problems})
        elif route == '/api/quick':
            self.send(200, archive.quick_listing(params.get('bucket', 'pending')))
        elif route == '/api/artworks':
            self.send(200, archive.listing(params))
        elif route.startswith('/api/artworks/'):
            self.send(200, archive.detail(route.rsplit('/', 1)[1]))
        elif route == '/api/analysis':
            self.send(200, archive.analysis(params))
        elif route == '/api/export':
            kind, fmt = params.get('kind', 'analysis'), params.get('format', 'json')
            if kind not in ('analysis', 'modifications', 'backup') or fmt not in ('md', 'json') or (kind == 'backup' and fmt != 'json'):
                raise ValueError('导出格式无效')
            packet = archive.store.backup() if kind == 'backup' else archive.modifications(params) if kind == 'modifications' else archive.analysis(params)
            stamp = packet['exported_at'].replace(':', '').replace('+', '_')
            body = markdown(packet) if fmt == 'md' else json.dumps(packet, ensure_ascii=False, indent=2)
            self.send(200, body, 'text/markdown; charset=utf-8' if fmt == 'md' else 'application/json; charset=utf-8',
                      f'arco-{kind}-{stamp}.{fmt}')
        elif route.startswith('/media/'):
            self.media(route.rsplit('/', 1)[1], params.get('size') == 'thumb')
        elif route.startswith('/exports/'):
            name = route.removeprefix('/exports/')
            directory = archive.data_dir / 'exports'
            file = (directory / name).resolve()
            if file.parent != directory.resolve() or file.suffix not in ('.md', '.json') or not name.startswith('arco-') or not file.is_file():
                raise KeyError('导出文件不存在')
            self.send(200, file.read_bytes(), 'text/markdown; charset=utf-8' if file.suffix == '.md' else 'application/json; charset=utf-8', name)
        elif route in ('/', '/index.html', '/app.js', '/style.css'):
            file = STATIC / ('index.html' if route == '/' else route.lstrip('/'))
            self.send(200, file.read_bytes(), {'html': 'text/html', 'js': 'text/javascript', 'css': 'text/css'}[file.suffix[1:]] + '; charset=utf-8')
        else:
            self.send(404, {'error': '页面不存在'})

    def media(self, asset_id, thumbnail):
        asset = self.server.archive.integrity(asset_id)
        if not asset['exists']:
            raise KeyError('图片文件缺失')
        path = Path(asset['path'])
        if thumbnail:
            from PIL import Image, ImageOps
            cache_dir = self.server.archive.data_dir / 'thumbnails'
            cache_dir.mkdir(parents=True, exist_ok=True)
            # Cache by actual bytes, so a changed source cannot reuse a stale thumbnail.
            target = cache_dir / (asset['actual_sha256'] + '-512-v1.jpg')
            with self.server.thumbnail_lock:
                if not target.is_file():
                    with Image.open(path) as image:
                        image = ImageOps.exif_transpose(image)
                        image.thumbnail((512, 512), Image.Resampling.LANCZOS)
                        if image.mode in ('RGBA', 'LA') or (image.mode == 'P' and 'transparency' in image.info):
                            rgba = image.convert('RGBA')
                            base = Image.new('RGB', rgba.size, '#e9e9e7')
                            base.paste(rgba, mask=rgba.getchannel('A'))
                            image = base
                        else:
                            image = image.convert('RGB')
                        temp = target.with_suffix('.tmp')
                        image.save(temp, format='JPEG', quality=85)
                        temp.replace(target)
            path = target
        mime = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        self.send(200, path.read_bytes(), mime, cache=thumbnail)

    def do_POST(self):
        if not self.valid_host() or not secrets.compare_digest(self.headers.get('X-Arco-Token', ''), self.server.token):
            self.send(403, {'error': '本机页面凭证无效，请刷新页面'})
            return
        origin = self.headers.get('Origin')
        if origin and origin not in (f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'):
            self.send(403, {'error': '请求来源无效'})
            return
        try:
            size = int(self.headers.get('Content-Length', 0))
            if not 0 < size <= 16 * 1024 * 1024:
                raise ValueError('请求大小无效')
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError('请求格式无效')
            route = urlparse(self.path).path
            archive = self.server.archive
            if route.startswith('/api/review/'):
                self.send(200, archive.save(route.rsplit('/', 1)[1], data.get('review'), data.get('revision')))
            elif route == '/api/refresh':
                self.send(200, archive.refresh())
            elif route == '/api/session':
                if len(json.dumps(data)) > 20000:
                    raise ValueError('会话记录过长')
                archive.store.set_setting('session', data)
                self.send(200, {'saved': True})
            elif route == '/api/shutdown':
                self.send(200, {'stopped': True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            elif route == '/api/restore':
                for flag in ('overwrite', 'dry_run'):
                    if type(data.get(flag, flag == 'dry_run')) is not bool:
                        raise ValueError('恢复选项无效')
                self.send(200, archive.store.restore(data.get('packet'), archive.items,
                    data.get('overwrite', False), data.get('dry_run', True)))
            elif route == '/api/export':
                kind, fmt = data.get('kind'), data.get('format')
                if kind not in ('analysis', 'modifications', 'backup') or fmt not in ('md', 'json') or (kind == 'backup' and fmt != 'json'):
                    raise ValueError('导出格式无效')
                params = data.get('filters', {})
                if not isinstance(params, dict):
                    raise ValueError('导出筛选格式无效')
                packet = archive.store.backup() if kind == 'backup' else archive.modifications(params) if kind == 'modifications' else archive.analysis(params)
                stamp = packet['exported_at'].replace(':', '').replace('+', '_')
                name = f'arco-{kind}-{stamp}-{secrets.token_hex(4)}.{fmt}'
                directory = archive.data_dir / 'exports'
                directory.mkdir(parents=True, exist_ok=True)
                file = directory / name
                body = markdown(packet) if fmt == 'md' else json.dumps(packet, ensure_ascii=False, indent=2)
                temp = file.with_suffix('.tmp')
                temp.write_text(body, encoding='utf-8')
                temp.replace(file)
                self.send(200, {'path': str(file), 'download_url': '/exports/' + name, 'filename': name})
            else:
                self.send(404, {'error': '接口不存在'})
        except Conflict as exc:
            self.send(409, {'error': str(exc)})
        except KeyError as exc:
            self.send(404, {'error': str(exc)})
        except (ValueError, TypeError) as exc:
            self.send(400, {'error': str(exc)})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            self.log_error('POST failed: %s', exc)
            self.send(500, {'error': '保存或读取失败，草稿应保留在页面；请重试或检查服务日志'})


def main():
    parser = argparse.ArgumentParser(description='Arco 本机图片审阅工具')
    parser.add_argument('--root', type=Path, default=APP_DIR.parents[1])
    parser.add_argument('--data-dir', type=Path, default=APP_DIR / '.local')
    parser.add_argument('--port', type=int, default=8931)
    parser.add_argument('--open', action='store_true')
    parser.add_argument('--audit', action='store_true')
    parser.add_argument('--hashes', action='store_true')
    args = parser.parse_args()
    archive = Archive(args.root, args.data_dir)
    if args.audit:
        report = archive.audit(args.hashes)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if report['failures'] or report['record_problems'] else 0
    from PIL import Image  # Fail before publishing the instance if dependencies are missing.
    try:
        server = Server(archive, args.port)
    except OSError:
        if args.port == 0:
            raise
        server = Server(archive, 0)
    url = f'http://127.0.0.1:{server.server_port}'
    args.data_dir.mkdir(parents=True, exist_ok=True)
    instance = args.data_dir / 'instance.json'
    temp = instance.with_suffix('.tmp')
    temp.write_text(json.dumps({'url': url, 'pid': os.getpid(), 'root': str(archive.root)}, ensure_ascii=False), encoding='utf-8')
    temp.replace(instance)
    print(f'Arco Review ready: {url}', flush=True)
    if args.open:
        webbrowser.open(url + '/#quick')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        try:
            if json.loads(instance.read_text(encoding='utf-8'))['pid'] == os.getpid():
                instance.unlink()
        except (OSError, ValueError, KeyError):
            pass
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
