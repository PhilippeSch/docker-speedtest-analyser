#!/usr/bin/env python3

# Serves the web interface, runs the speedtest periodically and on demand via /run_speedtest.
# Replaces the former nginx + lua + crond setup.

import os
import json
import time
import threading
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

import speedtestRunner
from speedtestRunner import log

WEBROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
#only these paths are served, everything else (scripts, config, ...) stays private
PUBLIC_PREFIXES = ('/index.html', '/favicon.ico', '/js/', '/data/', '/node_modules/')

testLock = threading.Lock()


def runLocked():
        #returns the new csv row, or None if a test was already running (we then wait for it to finish)
        if testLock.acquire(blocking=False):
                try:
                        return speedtestRunner.runWithRetries()
                finally:
                        testLock.release()
        with testLock:
                return None


def getIntervalSeconds():
        #CRONJOB_ITERATION: minutes between speedtests, default hourly
        try:
                minutes = int(os.environ.get('CRONJOB_ITERATION') or 60)
        except ValueError:
                log('invalid CRONJOB_ITERATION, using 60 minutes')
                minutes = 60
        return max(1, minutes) * 60


def scheduler():
        interval = getIntervalSeconds()
        log('speedtest runs every %d minutes' % (interval // 60))
        while True:
                #align to the interval like the former cronjob (e.g. :00, :15, :30, :45)
                now = time.time()
                time.sleep(interval - now % interval)
                try:
                        runLocked()
                except Exception as e:
                        log('scheduled speedtest failed: %s' % e)


class Handler(SimpleHTTPRequestHandler):

        def do_GET(self):
                path = self.path.split('?', 1)[0]
                if path == '/run_speedtest':
                        return self.runSpeedtest()
                if path == '/':
                        self.path = '/index.html'
                elif not path.startswith(PUBLIC_PREFIXES) or '..' in path:
                        return self.send_error(404)
                if path == '/data/appConfig.js' and not os.path.isfile(os.path.join(WEBROOT, 'data', 'appConfig.js')):
                        #optional user config, answer with an empty script instead of a 404
                        return self.sendBody(200, b'', 'application/javascript')
                return super().do_GET()

        def do_HEAD(self):
                self.send_error(405)

        def end_headers(self):
                #always deliver fresh results
                if self.path.startswith('/data/'):
                        self.send_header('Cache-Control', 'no-store')
                super().end_headers()

        def runSpeedtest(self):
                try:
                        row = runLocked()
                        body = {'status': 'ok', 'result': row}
                        code = 200
                except Exception as e:
                        body = {'status': 'error', 'message': str(e)}
                        code = 500
                self.sendBody(code, json.dumps(body).encode(), 'application/json')

        def sendBody(self, code, body, contentType):
                self.send_response(code)
                self.send_header('Content-Type', contentType)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        def log_message(self, format, *args):
                #keep the container log readable, only log errors
                pass

        def log_error(self, format, *args):
                log('http: ' + format % args)


if __name__ == '__main__':
        port = int(os.environ.get('PORT', '80'))
        threading.Thread(target=scheduler, daemon=True).start()
        server = ThreadingHTTPServer(('', port), partial(Handler, directory=WEBROOT))
        log('web interface listening on port %d' % port)
        server.serve_forever()
