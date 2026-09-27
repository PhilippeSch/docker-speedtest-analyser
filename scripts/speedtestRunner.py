#!/usr/bin/env python3

# Script originally provided by AlekseyP
# https://www.reddit.com/r/technology/comments/43fi39/i_set_up_my_raspberry_pi_to_automatically_tweet/
# modifications by roest - https://github.com/roest01

import os
import sys
import csv
import json
import shlex
import datetime
import subprocess
import time
import traceback

#static values
CSV_FIELDNAMES = ["timestamp", "ping", "download", "upload"]
FILEPATH = os.path.dirname(os.path.abspath(__file__)) + '/../data/result.csv'
OOKLA_BIN = os.environ.get('OOKLA_BIN', '/opt/ookla/speedtest')
OOKLA_TIMEOUT_SECONDS = 180
RETRY_DELAY_SECONDS = 30


def log(message):
        print('%s %s' % (datetime.datetime.now().isoformat(timespec='seconds'), message), flush=True)


def getEngines():
        #"auto" tries the official Ookla CLI first and falls back to speedtest-cli
        engine = os.environ.get('SPEEDTEST_ENGINE', 'auto').strip().lower()
        if engine == 'ookla':
                return [runOokla]
        if engine == 'speedtest-cli':
                return [runSpeedtestCli]
        return [runOokla, runSpeedtestCli]


def getServerId():
        return os.environ.get('SPEEDTEST_SERVER_ID', '').strip()


def runOokla():
        if not os.access(OOKLA_BIN, os.X_OK):
                raise RuntimeError('Ookla CLI not found at %s' % OOKLA_BIN)

        cmd = [OOKLA_BIN, '--accept-license', '--accept-gdpr', '--format=json', '--progress=no']
        if getServerId():
                cmd.append('--server-id=%s' % getServerId())
        cmd += shlex.split(os.environ.get('SPEEDTEST_PARAMS', ''))

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=OOKLA_TIMEOUT_SECONDS)
        if proc.returncode != 0:
                raise RuntimeError('Ookla CLI exited with %d: %s' % (proc.returncode, (proc.stderr or proc.stdout).strip()))

        #the CLI may print log lines before the result, the result is the last JSON line
        result = None
        for line in proc.stdout.splitlines():
                line = line.strip()
                if line.startswith('{'):
                        data = json.loads(line)
                        if data.get('type') == 'result':
                                result = data
        if result is None:
                raise RuntimeError('Ookla CLI returned no result: %s' % proc.stdout.strip())

        #bandwidth is reported in bytes per second
        return {
                'ping': result['ping']['latency'],
                'download': result['download']['bandwidth'] * 8 / 1000 / 1000,
                'upload': result['upload']['bandwidth'] * 8 / 1000 / 1000,
                'server': '%s (%s)' % (result['server']['name'], result['server']['location'])}


def runSpeedtestCli():
        from speedtest import Speedtest

        servers = [int(getServerId())] if getServerId() else []

        #speedtest.net rejects plain HTTP requests with "403 Forbidden", so use HTTPS
        s = Speedtest(secure=True)
        s.get_servers(servers)
        s.get_best_server()
        s.download()
        s.upload()
        result = s.results.dict()

        return {
                'ping': result['ping'],
                'download': result['download'] / 1000 / 1000,
                'upload': result['upload'] / 1000 / 1000,
                'server': '%s (%s)' % (result['server']['sponsor'], result['server']['name'])}


def writeResult(result):
        csv_data_dict = {
                CSV_FIELDNAMES[0]: round(time.time() * 1000, 3),
                CSV_FIELDNAMES[1]: round(result['ping'], 2),
                CSV_FIELDNAMES[2]: round(result['download'], 2),
                CSV_FIELDNAMES[3]: round(result['upload'], 2)}

        #write testdata to file
        isFileEmpty = not os.path.isfile(FILEPATH) or os.stat(FILEPATH).st_size == 0

        with open(FILEPATH, "a") as f:
                csv_writer = csv.DictWriter(f, delimiter=',', lineterminator='\n', fieldnames=CSV_FIELDNAMES)
                if isFileEmpty:
                        csv_writer.writeheader()

                csv_writer.writerow(csv_data_dict)

        return csv_data_dict


def runSpeedtest():
        log('--- running speedtest ---')

        errors = []
        for engine in getEngines():
                try:
                        result = engine()
                        break
                except Exception as e:
                        log('%s failed: %s' % (engine.__name__, e))
                        errors.append('%s: %s' % (engine.__name__, e))
        else:
                raise RuntimeError('; '.join(errors))

        row = writeResult(result)

        #print testdata
        log('--- Result (%s) ---' % result['server'])
        log('Ping: %.2f [ms]' % row['ping'])
        log('Download: %.2f [Mbit/s]' % row['download'])
        log('Upload: %.2f [Mbit/s]' % row['upload'])
        return row


def runWithRetries():
        attempts = max(1, int(os.environ.get('SPEEDTEST_RETRIES', '3')))
        for attempt in range(1, attempts + 1):
                try:
                        row = runSpeedtest()
                        log('speedtest complete')
                        return row
                except Exception:
                        log('speedtest attempt %d/%d failed:' % (attempt, attempts))
                        traceback.print_exc()
                        sys.stderr.flush()
                        if attempt < attempts:
                                time.sleep(RETRY_DELAY_SECONDS)

        raise RuntimeError('speedtest failed after %d attempts' % attempts)


if __name__ == '__main__':
        try:
                runWithRetries()
        except RuntimeError as e:
                log(str(e))
                sys.exit(1)
