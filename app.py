"""
Flask API for Meta Ads Data Fetcher — deployed on Railway.
Google Sheet buttons call these endpoints instead of running logic in Apps Script.
"""

import json
import os
import threading

from flask import Flask, jsonify, request

from config import ACCOUNTS, DATA_RETENTION_DAYS
from fetch_meta_data import (
    fetch_insights,
    fetch_platform_insights,
    get_gspread_client,
    get_spreadsheet,
    write_data,
    write_platform_data,
)

app = Flask(__name__)

API_SECRET = os.getenv('API_SECRET', '')


def check_auth():
    token = request.headers.get('X-API-Secret', '') or request.args.get('secret', '')
    if API_SECRET and token != API_SECRET:
        return False
    return True


@app.route('/')
def index():
    return jsonify({'status': 'ok', 'service': 'Meta Ads Fetcher'})


@app.route('/health')
def health():
    return jsonify({'status': 'healthy'})


@app.route('/fetch', methods=['GET', 'POST'])
def fetch():
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    account_idx = request.args.get('account', type=int)
    level = request.args.get('level')

    if account_idx is not None and (account_idx < 1 or account_idx > 3):
        return jsonify({'error': 'account must be 1, 2, or 3'}), 400
    if level and level not in ('campaign', 'adset', 'ad'):
        return jsonify({'error': 'level must be campaign, adset, or ad'}), 400

    def run_job():
        try:
            client = get_gspread_client()
            spreadsheet = get_spreadsheet(client)

            accounts = [ACCOUNTS[account_idx - 1]] if account_idx else ACCOUNTS
            levels = [level] if level else ['campaign', 'adset', 'ad']

            for acc in accounts:
                rpa = acc.get('real_purchase_action', '')
                for lv in levels:
                    data = fetch_insights(acc, lv)
                    write_data(spreadsheet, acc['name'], lv, data, rpa)

            print(f"Job done: account={account_idx}, level={level}")
        except Exception as e:
            print(f"Job failed: {e}")

    thread = threading.Thread(target=run_job)
    thread.start()

    return jsonify({
        'status': 'started',
        'account': account_idx or 'all',
        'level': level or 'all',
        'message': 'Fetch job started in background'
    })


@app.route('/fetch-sync', methods=['GET', 'POST'])
def fetch_sync():
    """Synchronous version — waits for completion. Use for testing."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    account_idx = request.args.get('account', type=int)
    level = request.args.get('level')

    try:
        client = get_gspread_client()
        spreadsheet = get_spreadsheet(client)

        accounts = [ACCOUNTS[account_idx - 1]] if account_idx else ACCOUNTS
        levels = [level] if level else ['campaign', 'adset', 'ad']

        results = []
        for acc in accounts:
            rpa = acc.get('real_purchase_action', '')
            for lv in levels:
                data = fetch_insights(acc, lv)
                write_data(spreadsheet, acc['name'], lv, data, rpa)
                results.append({'account': acc['name'], 'level': lv, 'rows': len(data)})

        return jsonify({'status': 'done', 'results': results})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/fetch-platform', methods=['GET', 'POST'])
def fetch_platform():
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    account_idx = request.args.get('account', type=int)

    if account_idx is not None and (account_idx < 1 or account_idx > 3):
        return jsonify({'error': 'account must be 1, 2, or 3'}), 400

    def run_job():
        try:
            client = get_gspread_client()
            spreadsheet = get_spreadsheet(client)

            accounts = [ACCOUNTS[account_idx - 1]] if account_idx else ACCOUNTS

            for acc in accounts:
                rpa = acc.get('real_purchase_action', '')
                for lv in ['campaign', 'adset']:
                    data = fetch_platform_insights(acc, lv)
                    write_platform_data(spreadsheet, acc['name'], lv, data, rpa)

            print(f"Platform job done: account={account_idx}")
        except Exception as e:
            print(f"Platform job failed: {e}")

    thread = threading.Thread(target=run_job)
    thread.start()

    return jsonify({
        'status': 'started',
        'account': account_idx or 'all',
        'message': 'Platform fetch job started in background'
    })


@app.route('/fetch-platform-sync', methods=['GET', 'POST'])
def fetch_platform_sync():
    """Synchronous version — waits for completion."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    account_idx = request.args.get('account', type=int)

    if account_idx is not None and (account_idx < 1 or account_idx > 3):
        return jsonify({'error': 'account must be 1, 2, or 3'}), 400

    try:
        client = get_gspread_client()
        spreadsheet = get_spreadsheet(client)

        accounts = [ACCOUNTS[account_idx - 1]] if account_idx else ACCOUNTS

        results = []
        for acc in accounts:
            rpa = acc.get('real_purchase_action', '')
            for lv in ['campaign', 'adset']:
                data = fetch_platform_insights(acc, lv)
                write_platform_data(spreadsheet, acc['name'], lv, data, rpa)
                results.append({'account': acc['name'], 'level': lv, 'rows': len(data)})

        return jsonify({'status': 'done', 'results': results})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
