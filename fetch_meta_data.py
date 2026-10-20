"""
Meta Ads Data Fetcher — runs locally, writes to Google Sheets via Service Account.
Usage:  python fetch_meta_data.py
        python fetch_meta_data.py --account 1          # single account
        python fetch_meta_data.py --account 1 --level campaign  # single level
"""

import argparse
import json
import sys
import time
from datetime import datetime, timedelta

import gspread
import requests
from google.oauth2.service_account import Credentials

from config import (
    ACCOUNTS, AD_HEADERS, ADSET_HEADERS, API_FIELDS, API_VERSION,
    CAMPAIGN_HEADERS, DATA_RETENTION_DAYS, GOOGLE_SERVICE_ACCOUNT_JSON,
    META_API_BASE, SERVICE_ACCOUNT_FILE, SPREADSHEET_ID,
)

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive',
]


def get_gspread_client():
    if GOOGLE_SERVICE_ACCOUNT_JSON:
        info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return gspread.authorize(creds)


def get_spreadsheet(client):
    try:
        return client.open_by_key(SPREADSHEET_ID)
    except gspread.SpreadsheetNotFound:
        print(f'Spreadsheet not found. Share it with the service account email.')
        sys.exit(1)


# ── Meta API ──────────────────────────────────────────────

AD_LEVEL_RETENTION_DAYS = 3

def fetch_insights(account, level):
    today = datetime.now()
    all_data = []
    days = AD_LEVEL_RETENTION_DAYS if level == 'ad' else DATA_RETENTION_DAYS

    for day_offset in range(days - 1, -1, -1):
        day = (today - timedelta(days=day_offset)).strftime('%Y-%m-%d')
        try:
            day_data = fetch_insights_for_day(account, level, day)
            all_data.extend(day_data)
            if day_data:
                print(f"    {day}: {len(day_data)} rows")
            else:
                print(f"    {day}: 0 rows")
        except Exception as e:
            print(f"    {day}: FAILED ({e}) — skipping")
        time.sleep(2)

    print(f"  {level}: fetched {len(all_data)} rows total")
    return all_data


def fetch_insights_for_day(account, level, day, retries=3):
    from config import AD_LEVEL_FIELDS
    fields = AD_LEVEL_FIELDS if level == 'ad' else API_FIELDS
    fields_param = ','.join(fields)
    time_range = f'{{"since":"{day}","until":"{day}"}}'

    limit = 500
    filtering = ''
    if level in ('ad', 'adset'):
        filtering = f'&filtering=[{{"field":"impressions","operator":"GREATER_THAN","value":"0"}}]'

    # For ad level, use async report to handle large data
    if level == 'ad':
        return fetch_async_report(account, level, fields_param, time_range, filtering, day, retries)

    url = (
        f"{META_API_BASE}/act_{account['account_id']}/insights"
        f"?fields={fields_param}"
        f"&level={level}"
        f"&time_range={time_range}"
        f"&time_increment=1"
        f"&breakdowns=hourly_stats_aggregated_by_advertiser_time_zone"
        f"&limit={limit}"
        f"{filtering}"
        f"&access_token={account['access_token']}"
    )

    data = []
    while url:
        for attempt in range(retries):
            try:
                resp = requests.get(url, timeout=180)
                body = resp.json()
            except Exception as e:
                if attempt < retries - 1:
                    wait = (attempt + 1) * 15
                    print(f"      Retry {attempt + 1}/{retries} in {wait}s: {e}")
                    time.sleep(wait)
                    continue
                raise

            if 'error' in body:
                err_msg = body['error'].get('message', 'Unknown')
                if attempt < retries - 1:
                    wait = (attempt + 1) * 15
                    print(f"      Retry {attempt + 1}/{retries} in {wait}s: {err_msg}")
                    time.sleep(wait)
                    continue
                raise RuntimeError(f"Meta API error ({level}, {day}): {err_msg}")
            break

        data.extend(body.get('data', []))
        url = body.get('paging', {}).get('next')
        if url:
            time.sleep(1.5)

    return data


def fetch_async_report(account, level, fields_param, time_range, filtering, day, retries=3):
    """Use Meta's async report endpoint for large datasets (ad level)."""

    # Step 1: Create async report
    create_url = (
        f"{META_API_BASE}/act_{account['account_id']}/insights"
        f"?fields={fields_param}"
        f"&level={level}"
        f"&time_range={time_range}"
        f"&time_increment=1"
        f"&breakdowns=hourly_stats_aggregated_by_advertiser_time_zone"
        f"{filtering}"
        f"&access_token={account['access_token']}"
    )

    resp = requests.post(create_url, timeout=120)
    body = resp.json()

    if 'error' in body:
        raise RuntimeError(f"Async report create error ({day}): {body['error']['message']}")

    report_id = body.get('report_run_id')
    if not report_id:
        raise RuntimeError(f"No report_run_id returned for {day}")

    print(f"      Async report created: {report_id}")

    # Step 2: Poll until complete
    for poll in range(60):
        time.sleep(10)
        status_url = f"{META_API_BASE}/{report_id}?access_token={account['access_token']}"
        status_resp = requests.get(status_url, timeout=60)
        status_body = status_resp.json()

        pct = status_body.get('async_percent_completion', 0)
        status = status_body.get('async_status', 'Unknown')

        if status == 'Job Completed':
            print(f"      Report ready (100%)")
            break
        elif status == 'Job Failed':
            raise RuntimeError(f"Async report failed for {day}")
        else:
            if poll % 3 == 0:
                print(f"      Waiting... {pct}% ({status})")
    else:
        raise RuntimeError(f"Async report timed out for {day}")

    # Step 3: Fetch results with pagination
    data = []
    result_url = f"{META_API_BASE}/{report_id}/insights?limit=500&access_token={account['access_token']}"

    while result_url:
        for attempt in range(retries):
            try:
                r = requests.get(result_url, timeout=180)
                result_body = r.json()
            except Exception as e:
                if attempt < retries - 1:
                    time.sleep(15)
                    continue
                raise

            if 'error' in result_body:
                if attempt < retries - 1:
                    time.sleep(15)
                    continue
                raise RuntimeError(f"Async result fetch error: {result_body['error']['message']}")
            break

        data.extend(result_body.get('data', []))
        result_url = result_body.get('paging', {}).get('next')
        if result_url:
            time.sleep(1)

    return data


# ── Platform/Placement fetch (daily, no hourly) ──────────

def fetch_platform_insights(account, level):
    """Fetch data with publisher_platform + platform_position breakdown, daily."""
    today = datetime.now()
    all_data = []
    days = AD_LEVEL_RETENTION_DAYS if level == 'ad' else DATA_RETENTION_DAYS

    for day_offset in range(days - 1, -1, -1):
        day = (today - timedelta(days=day_offset)).strftime('%Y-%m-%d')
        try:
            day_data = fetch_platform_for_day(account, level, day)
            all_data.extend(day_data)
            if day_data:
                print(f"    {day}: {len(day_data)} rows")
            else:
                print(f"    {day}: 0 rows")
        except Exception as e:
            print(f"    {day}: FAILED ({e}) — skipping")
        time.sleep(2)

    print(f"  platform {level}: fetched {len(all_data)} rows total")
    return all_data


def fetch_platform_for_day(account, level, day, retries=3):
    from config import PLATFORM_FIELDS
    fields_param = ','.join(PLATFORM_FIELDS)
    time_range = f'{{"since":"{day}","until":"{day}"}}'
    filtering = '&filtering=[{"field":"impressions","operator":"GREATER_THAN","value":"0"}]'

    url = (
        f"{META_API_BASE}/act_{account['account_id']}/insights"
        f"?fields={fields_param}"
        f"&level={level}"
        f"&time_range={time_range}"
        f"&time_increment=1"
        f"&breakdowns=publisher_platform,platform_position"
        f"&limit=500"
        f"{filtering}"
        f"&access_token={account['access_token']}"
    )

    data = []
    while url:
        for attempt in range(retries):
            try:
                resp = requests.get(url, timeout=180)
                body = resp.json()
            except Exception as e:
                if attempt < retries - 1:
                    wait = (attempt + 1) * 15
                    print(f"      Retry {attempt + 1}/{retries} in {wait}s: {e}")
                    time.sleep(wait)
                    continue
                raise

            if 'error' in body:
                err_msg = body['error'].get('message', 'Unknown')
                if 'reduce' in err_msg.lower():
                    print(f"      Sync too large, switching to async for {day}")
                    return fetch_platform_async(account, level, fields_param, time_range, filtering, day, retries)
                if attempt < retries - 1:
                    wait = (attempt + 1) * 15
                    print(f"      Retry {attempt + 1}/{retries} in {wait}s: {err_msg}")
                    time.sleep(wait)
                    continue
                raise RuntimeError(f"Meta API error (platform {level}, {day}): {err_msg}")
            break

        data.extend(body.get('data', []))
        url = body.get('paging', {}).get('next')
        if url:
            time.sleep(1.5)

    return data


def fetch_platform_async(account, level, fields_param, time_range, filtering, day, retries=3):
    create_url = (
        f"{META_API_BASE}/act_{account['account_id']}/insights"
        f"?fields={fields_param}"
        f"&level={level}"
        f"&time_range={time_range}"
        f"&time_increment=1"
        f"&breakdowns=publisher_platform,platform_position"
        f"{filtering}"
        f"&access_token={account['access_token']}"
    )

    resp = requests.post(create_url, timeout=120)
    body = resp.json()
    if 'error' in body:
        raise RuntimeError(f"Async create error ({day}): {body['error']['message']}")

    report_id = body.get('report_run_id')
    if not report_id:
        raise RuntimeError(f"No report_run_id for platform {day}")

    print(f"      Async report created: {report_id}")

    for poll in range(60):
        time.sleep(10)
        status_url = f"{META_API_BASE}/{report_id}?access_token={account['access_token']}"
        status_resp = requests.get(status_url, timeout=60)
        status_body = status_resp.json()
        status = status_body.get('async_status', 'Unknown')
        if status == 'Job Completed':
            print(f"      Report ready (100%)")
            break
        elif status == 'Job Failed':
            raise RuntimeError(f"Async report failed for platform {day}")
    else:
        raise RuntimeError(f"Async report timed out for platform {day}")

    data = []
    result_url = f"{META_API_BASE}/{report_id}/insights?limit=500&access_token={account['access_token']}"
    while result_url:
        r = requests.get(result_url, timeout=180)
        result_body = r.json()
        if 'error' in result_body:
            raise RuntimeError(f"Async result error: {result_body['error']['message']}")
        data.extend(result_body.get('data', []))
        result_url = result_body.get('paging', {}).get('next')
        if result_url:
            time.sleep(1)

    return data


# ── Row mappers ───────────────────────────────────────────

def _get_action(actions, action_type):
    if not actions:
        return 0
    for a in actions:
        if a.get('action_type') == action_type:
            return float(a.get('value', 0))
    return 0


def _safe_div(n, d):
    return round(n / d, 2) if d else ''


def _safe_pct(n, d):
    return f"{round(n / d * 100, 2)}%" if d else ''


def _r(val):
    if val == '' or val is None:
        return ''
    return round(float(val), 2)


def _common_metrics(item, real_purchase_action=''):
    spend = float(item.get('spend', 0) or 0)
    impressions = float(item.get('impressions', 0) or 0)
    reach = float(item.get('reach', 0) or 0)
    frequency = float(item.get('frequency', 0) or 0)

    actions = item.get('actions', []) or []
    action_values = item.get('action_values', []) or []
    cost_per_action = item.get('cost_per_action_type', []) or []

    purchases = _get_action(actions, 'purchase') or _get_action(actions, 'omni_purchase')
    link_clicks = float(item.get('inline_link_clicks', 0) or 0) or _get_action(actions, 'link_click')
    landing_page_views = _get_action(actions, 'landing_page_view')
    adds_to_cart = _get_action(actions, 'add_to_cart') or _get_action(actions, 'omni_add_to_cart')
    checkouts = _get_action(actions, 'initiate_checkout') or _get_action(actions, 'omni_initiated_checkout')
    adds_payment = _get_action(actions, 'add_payment_info')

    purchase_value = _get_action(action_values, 'purchase') or _get_action(action_values, 'omni_purchase')
    cost_per_purchase = _get_action(cost_per_action, 'purchase') or _get_action(cost_per_action, 'omni_purchase')

    if real_purchase_action:
        real_purchases = _get_action(actions, real_purchase_action)
    else:
        real_purchases = purchases

    cpm = float(item.get('cpm', 0) or 0)
    cpc_link = float(item.get('cost_per_inline_link_click', 0) or 0) or _safe_div(spend, link_clicks)
    ctr_link = float(item.get('inline_link_click_ctr', 0) or 0)

    return {
        'spend': spend,
        'impressions': impressions,
        'reach': reach,
        'frequency': frequency,
        'purchases': purchases or '',
        'link_clicks': link_clicks or '',
        'landing_page_views': landing_page_views or '',
        'adds_to_cart': adds_to_cart or '',
        'checkouts': checkouts or '',
        'adds_payment': adds_payment or '',
        'purchase_value': _r(purchase_value) if purchase_value else '',
        'cost_per_purchase': _r(cost_per_purchase) if cost_per_purchase else '',
        'real_purchases': real_purchases or '',
        'real_cpt': _safe_div(spend, real_purchases),
        'cvr': _safe_pct(purchases, link_clicks),
        'c2v_ratio': _safe_pct(landing_page_views, link_clicks),
        'purchase_roas': _safe_div(purchase_value, spend),
        'cpm': _r(cpm),
        'cpc_link': _r(cpc_link),
        'ctr_link': f"{_r(ctr_link)}%" if ctr_link else '',
    }


def map_campaign_row(item, real_purchase_action=''):
    m = _common_metrics(item, real_purchase_action)
    created = (item.get('created_time') or '')[:10]
    return [
        item.get('date_start', ''),
        item.get('hourly_stats_aggregated_by_advertiser_time_zone', ''),
        item.get('campaign_name', ''),
        item.get('campaign_id', ''),
        '',  # Delivery
        '',  # Budget
        _r(m['spend']),
        m['real_purchases'], m['purchases'],
        m['real_cpt'], m['cost_per_purchase'],
        m['impressions'] or '', m['frequency'],
        m['cpm'], m['cpc_link'], m['ctr_link'],
        m['cvr'], m['link_clicks'], m['landing_page_views'],
        m['c2v_ratio'], m['purchase_roas'],
        m['adds_to_cart'], m['checkouts'], m['adds_payment'],
        created, m['purchase_value'],
    ]


def map_adset_row(item, real_purchase_action=''):
    m = _common_metrics(item, real_purchase_action)
    return [
        item.get('date_start', ''),
        item.get('hourly_stats_aggregated_by_advertiser_time_zone', ''),
        item.get('adset_name', ''),
        item.get('adset_id', ''),
        item.get('campaign_name', ''),
        item.get('campaign_id', ''),
        '',  # Delivery
        '',  # Budget
        _r(m['spend']),
        m['real_purchases'], m['purchases'],
        m['real_cpt'], m['cost_per_purchase'],
        m['impressions'] or '', m['frequency'],
        m['cpm'], m['cpc_link'], m['ctr_link'],
        m['cvr'], m['link_clicks'], m['landing_page_views'],
        m['c2v_ratio'], m['purchase_roas'],
        m['adds_to_cart'], m['checkouts'], m['adds_payment'],
        m['purchase_value'],
    ]


def map_ad_row(item, real_purchase_action=''):
    m = _common_metrics(item, real_purchase_action)
    return [
        item.get('date_start', ''),
        item.get('hourly_stats_aggregated_by_advertiser_time_zone', ''),
        item.get('ad_name', ''),
        item.get('ad_id', ''),
        item.get('adset_name', ''),
        item.get('adset_id', ''),
        item.get('campaign_name', ''),
        item.get('campaign_id', ''),
        _r(m['spend']),
        m['real_purchases'], m['purchases'],
        m['real_cpt'], m['cost_per_purchase'],
        m['ctr_link'], m['cvr'],
        m['purchase_roas'],
        m['adds_to_cart'], m['checkouts'], m['adds_payment'],
        m['purchase_value'],
    ]


# ── Platform/Placement row mappers ────────────────────────

def map_platform_campaign_row(item, real_purchase_action=''):
    m = _common_metrics(item, real_purchase_action)
    return [
        item.get('date_start', ''),
        item.get('publisher_platform', ''),
        item.get('platform_position', ''),
        item.get('campaign_name', ''),
        item.get('campaign_id', ''),
        _r(m['spend']), m['impressions'] or '', m['reach'] or '',
        m['frequency'], m['cpm'],
        m['real_purchases'], m['purchases'], m['real_cpt'], m['cost_per_purchase'],
        m['link_clicks'], m['ctr_link'], m['cvr'],
        m['purchase_roas'], m['purchase_value'],
    ]


def map_platform_adset_row(item, real_purchase_action=''):
    m = _common_metrics(item, real_purchase_action)
    return [
        item.get('date_start', ''),
        item.get('publisher_platform', ''),
        item.get('platform_position', ''),
        item.get('adset_name', ''),
        item.get('adset_id', ''),
        item.get('campaign_name', ''),
        item.get('campaign_id', ''),
        _r(m['spend']), m['impressions'] or '', m['reach'] or '',
        m['frequency'], m['cpm'],
        m['real_purchases'], m['purchases'], m['real_cpt'], m['cost_per_purchase'],
        m['link_clicks'], m['ctr_link'], m['cvr'],
        m['purchase_roas'], m['purchase_value'],
    ]


LEVEL_CONFIG = {
    'campaign': {'headers': CAMPAIGN_HEADERS, 'mapper': map_campaign_row, 'id_col': 3, 'suffix': 'Campaigns'},
    'adset':    {'headers': ADSET_HEADERS,    'mapper': map_adset_row,    'id_col': 3, 'suffix': 'Ad Sets'},
    'ad':       {'headers': AD_HEADERS,       'mapper': map_ad_row,       'id_col': 3, 'suffix': 'Ads'},
}

from config import (
    PLATFORM_FIELDS, PLATFORM_CAMPAIGN_HEADERS, PLATFORM_ADSET_HEADERS,
)

PLATFORM_LEVEL_CONFIG = {
    'campaign': {'headers': PLATFORM_CAMPAIGN_HEADERS, 'mapper': map_platform_campaign_row, 'id_col': 4, 'suffix': 'Platform Campaigns'},
    'adset':    {'headers': PLATFORM_ADSET_HEADERS,    'mapper': map_platform_adset_row,    'id_col': 4, 'suffix': 'Platform Ad Sets'},
}


# ── Sheet writing ─────────────────────────────────────────

def get_or_create_sheet(spreadsheet, sheet_name, headers):
    try:
        ws = spreadsheet.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(sheet_name, rows=1000, cols=len(headers))
        ws.append_row(headers, value_input_option='USER_ENTERED')
        ws.format('1', {'textFormat': {'bold': True}})
        ws.freeze(rows=1)
    return ws


def write_data(spreadsheet, account_name, level, data, real_purchase_action=''):
    cfg = LEVEL_CONFIG[level]
    sheet_name = f"{account_name} — {cfg['suffix']}"
    headers = cfg['headers']
    mapper = cfg['mapper']
    id_col = cfg['id_col']

    ws = get_or_create_sheet(spreadsheet, sheet_name, headers)

    rows = [mapper(item, real_purchase_action) for item in data]
    if not rows:
        print(f"  {sheet_name}: no data")
        return

    # Convert everything to str for key matching
    def make_key(r):
        return f"{r[id_col]}_{r[0]}_{r[1]}"

    # Read existing data
    existing_values = ws.get_all_values()
    existing_keys = {}
    for idx, row in enumerate(existing_values[1:], start=2):  # skip header, 1-indexed in sheets
        if len(row) > max(id_col, 1):
            k = f"{row[id_col]}_{row[0]}_{row[1]}"
            existing_keys[k] = idx

    rows_to_update = []
    rows_to_insert = []

    for row in rows:
        # Convert all values to strings for the sheet
        str_row = [str(v) if v != '' else '' for v in row]
        key = make_key(str_row)

        if key in existing_keys:
            rows_to_update.append((existing_keys[key], str_row))
        else:
            rows_to_insert.append(str_row)

    # Batch update existing rows
    if rows_to_update:
        batch = []
        for row_num, values in rows_to_update:
            batch.append({
                'range': f"A{row_num}:{gspread.utils.rowcol_to_a1(row_num, len(values)).split('!')[0] if '!' in gspread.utils.rowcol_to_a1(row_num, len(values)) else gspread.utils.rowcol_to_a1(row_num, len(values))}",
                'values': [values],
            })
        # gspread batch_update
        if batch:
            ws.batch_update(batch, value_input_option='USER_ENTERED')
        print(f"  {sheet_name}: updated {len(rows_to_update)} rows")

    # Insert new rows at top (row 2) — newest first
    if rows_to_insert:
        rows_to_insert.sort(key=lambda r: (r[0], r[1]), reverse=True)
        ws.insert_rows(rows_to_insert, row=2, value_input_option='USER_ENTERED')
        print(f"  {sheet_name}: inserted {len(rows_to_insert)} new rows")


# ── Purge old data ────────────────────────────────────────

def purge_old_data(spreadsheet):
    cutoff = (datetime.now() - timedelta(days=DATA_RETENTION_DAYS)).strftime('%Y-%m-%d')
    print(f"\nPurging data older than {cutoff}...")

    for ws in spreadsheet.worksheets():
        all_values = ws.get_all_values()
        if len(all_values) <= 1:
            continue

        headers = all_values[0]
        if 'Date' not in headers:
            continue

        date_idx = headers.index('Date')
        rows_to_keep = []
        delete_count = 0

        for row in all_values[1:]:
            if len(row) > date_idx and row[date_idx] and row[date_idx] < cutoff:
                delete_count += 1
            else:
                rows_to_keep.append(row)

        if delete_count == 0:
            continue

        ws.clear()
        ws.append_row(headers, value_input_option='USER_ENTERED')
        if rows_to_keep:
            ws.append_rows(rows_to_keep, value_input_option='USER_ENTERED')
        ws.format('1', {'textFormat': {'bold': True}})
        ws.freeze(rows=1)
        print(f"  {ws.title}: deleted {delete_count} old rows ({len(rows_to_keep)} kept)")
        time.sleep(2)


# ── Main ──────────────────────────────────────────────────

def write_platform_data(spreadsheet, account_name, level, data, real_purchase_action=''):
    cfg = PLATFORM_LEVEL_CONFIG[level]
    sheet_name = f"{account_name} — {cfg['suffix']}"
    headers = cfg['headers']
    mapper = cfg['mapper']
    id_col = cfg['id_col']

    ws = get_or_create_sheet(spreadsheet, sheet_name, headers)

    rows = [mapper(item, real_purchase_action) for item in data]
    if not rows:
        print(f"  {sheet_name}: no data")
        return

    # Key: entity_id + date + platform + placement
    def make_key(r):
        return f"{r[id_col]}_{r[0]}_{r[1]}_{r[2]}"

    existing_values = ws.get_all_values()
    existing_keys = {}
    for idx, row in enumerate(existing_values[1:], start=2):
        if len(row) > max(id_col, 2):
            k = f"{row[id_col]}_{row[0]}_{row[1]}_{row[2]}"
            existing_keys[k] = idx

    rows_to_update = []
    rows_to_insert = []

    for row in rows:
        str_row = [str(v) if v != '' else '' for v in row]
        key = make_key(str_row)
        if key in existing_keys:
            rows_to_update.append((existing_keys[key], str_row))
        else:
            rows_to_insert.append(str_row)

    if rows_to_update:
        batch = []
        for row_num, values in rows_to_update:
            batch.append({
                'range': f"A{row_num}:{gspread.utils.rowcol_to_a1(row_num, len(values)).split('!')[0] if '!' in gspread.utils.rowcol_to_a1(row_num, len(values)) else gspread.utils.rowcol_to_a1(row_num, len(values))}",
                'values': [values],
            })
        if batch:
            ws.batch_update(batch, value_input_option='USER_ENTERED')
        print(f"  {sheet_name}: updated {len(rows_to_update)} rows")

    if rows_to_insert:
        rows_to_insert.sort(key=lambda r: (r[0], r[1], r[2]), reverse=True)
        ws.insert_rows(rows_to_insert, row=2, value_input_option='USER_ENTERED')
        print(f"  {sheet_name}: inserted {len(rows_to_insert)} new rows")


def process_account(spreadsheet, account, levels=None, include_platform=False):
    if not account['account_id'] or not account['access_token']:
        print(f"  Skipping {account['name']}: missing ID or token")
        return

    if levels is None:
        levels = ['campaign', 'adset', 'ad']

    rpa = account.get('real_purchase_action', '')

    for level in levels:
        try:
            data = fetch_insights(account, level)
            write_data(spreadsheet, account['name'], level, data, rpa)
            time.sleep(1)
        except Exception as e:
            print(f"  ERROR ({level}): {e}")

    if include_platform:
        for level in ['campaign', 'adset']:
            try:
                print(f"  Fetching platform/placement for {level}...")
                data = fetch_platform_insights(account, level)
                write_platform_data(spreadsheet, account['name'], level, data, rpa)
                time.sleep(1)
            except Exception as e:
                print(f"  ERROR (platform {level}): {e}")


def main():
    parser = argparse.ArgumentParser(description='Fetch Meta Ads data to Google Sheets')
    parser.add_argument('--account', type=int, choices=[1, 2, 3], help='Process single account (1, 2, or 3)')
    parser.add_argument('--level', choices=['campaign', 'adset', 'ad'], help='Process single level')
    parser.add_argument('--platform', action='store_true', help='Also fetch platform/placement breakdown')
    parser.add_argument('--platform-only', action='store_true', help='Only fetch platform/placement data')
    parser.add_argument('--purge-only', action='store_true', help='Only purge old data')
    args = parser.parse_args()

    print("Connecting to Google Sheets...")
    client = get_gspread_client()
    spreadsheet = get_spreadsheet(client)
    print(f'Connected to: {spreadsheet.title}')

    if args.purge_only:
        purge_old_data(spreadsheet)
        return

    levels = [args.level] if args.level else None

    if args.platform_only:
        accounts_to_process = [ACCOUNTS[args.account - 1]] if args.account else ACCOUNTS
        for account in accounts_to_process:
            print(f"\nProcessing platform data: {account['name']}")
            rpa = account.get('real_purchase_action', '')
            for level in ['campaign', 'adset']:
                try:
                    print(f"  Fetching platform/placement for {level}...")
                    data = fetch_platform_insights(account, level)
                    write_platform_data(spreadsheet, account['name'], level, data, rpa)
                    time.sleep(1)
                except Exception as e:
                    print(f"  ERROR (platform {level}): {e}")
        print("\nDone!")
        return

    if args.account:
        account = ACCOUNTS[args.account - 1]
        print(f"\nProcessing: {account['name']}")
        process_account(spreadsheet, account, levels, include_platform=args.platform)
    else:
        for account in ACCOUNTS:
            print(f"\nProcessing: {account['name']}")
            process_account(spreadsheet, account, levels, include_platform=args.platform)

    print("\nDone!")


if __name__ == '__main__':
    main()
