"""
Configuration — reads credentials from .env file or environment variables.
"""

import os
from dotenv import load_dotenv

load_dotenv()

SERVICE_ACCOUNT_FILE = 'project-cbc6e6d7-b810-47f6-a1f-b375a738dcf7.json'
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON', '')
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID', '1z8g3zYihQ-8mWMiJE_lRYvZhoZoLO7XshJbehPNuhaM')

API_VERSION = 'v21.0'
DATA_RETENTION_DAYS = 7
META_API_BASE = f'https://graph.facebook.com/{API_VERSION}'

ACCOUNTS = [
    {
        'name': 'Jaadu Diet',
        'account_id': os.getenv('ACCOUNT_1_ID', ''),
        'access_token': os.getenv('ACCOUNT_1_TOKEN', ''),
        'pixel_id': os.getenv('ACCOUNT_1_PIXEL_ID', ''),
        'real_purchase_action': 'offsite_conversion.custom.2105830093378790',
    },
    {
        'name': 'DBC 2',
        'account_id': os.getenv('ACCOUNT_2_ID', ''),
        'access_token': os.getenv('ACCOUNT_2_TOKEN', ''),
        'pixel_id': os.getenv('ACCOUNT_2_PIXEL_ID', ''),
        'real_purchase_action': 'offsite_conversion.custom.1054873367529454',
    },
    {
        'name': 'Chimal Bajjer',
        'account_id': os.getenv('ACCOUNT_3_ID', ''),
        'access_token': os.getenv('ACCOUNT_3_TOKEN', ''),
        'pixel_id': os.getenv('ACCOUNT_3_PIXEL_ID', ''),
        'real_purchase_action': 'offsite_conversion.custom.943944578339479',
    },
]

API_FIELDS = [
    'campaign_id', 'campaign_name',
    'adset_id', 'adset_name',
    'ad_id', 'ad_name',
    'objective', 'spend',
    'impressions', 'reach', 'frequency',
    'cpm', 'cpc', 'ctr',
    'actions', 'action_values', 'cost_per_action_type',
    'inline_link_clicks', 'inline_link_click_ctr',
    'cost_per_inline_link_click',
    'created_time',
]

AD_LEVEL_FIELDS = [
    'campaign_id', 'campaign_name',
    'adset_id', 'adset_name',
    'ad_id', 'ad_name',
    'spend',
    'inline_link_clicks', 'inline_link_click_ctr',
    'actions', 'action_values', 'cost_per_action_type',
]

CAMPAIGN_HEADERS = [
    'Date', 'Hour',
    'Campaign', 'Campaign ID',
    'Delivery', 'Budget',
    'Amount Spent',
    'Real Purchases', 'Purchases',
    'Real CPT', 'Cost per Result',
    'Impressions', 'Frequency',
    'CPM', 'CPC (Link Click)', 'CTR (Link Click-Through)',
    'CVR', 'Link Clicks', 'Website Landing Page Views',
    'C2V Ratio', 'Purchase ROAS',
    'Adds to Cart', 'Checkouts Initiated', 'Adds of Payment Info',
    'Date Created', 'Results Value',
]

ADSET_HEADERS = [
    'Date', 'Hour',
    'Ad Set', 'Ad Set ID',
    'Campaign', 'Campaign ID',
    'Delivery', 'Budget',
    'Amount Spent',
    'Real Purchases', 'Purchases',
    'Real CPT', 'Cost per Result',
    'Impressions', 'Frequency',
    'CPM', 'CPC (Link Click)', 'CTR (Link Click-Through)',
    'CVR', 'Link Clicks', 'Website Landing Page Views',
    'C2V Ratio', 'Purchase ROAS',
    'Adds to Cart', 'Checkouts Initiated', 'Adds of Payment Info',
    'Results Value',
]

AD_HEADERS = [
    'Date', 'Hour',
    'Ad', 'Ad ID',
    'Ad Set', 'Ad Set ID',
    'Campaign', 'Campaign ID',
    'Amount Spent',
    'Real Purchases', 'Purchases',
    'Real CPT', 'Cost per Result',
    'CTR (Link Click-Through)', 'CVR',
    'Purchase ROAS',
    'Adds to Cart', 'Checkouts Initiated', 'Adds of Payment Info',
    'Results Value',
]

PLATFORM_FIELDS = [
    'campaign_id', 'campaign_name',
    'adset_id', 'adset_name',
    'ad_id', 'ad_name',
    'spend', 'impressions', 'reach', 'frequency', 'cpm',
    'actions', 'action_values', 'cost_per_action_type',
    'inline_link_clicks', 'inline_link_click_ctr',
]

PLATFORM_CAMPAIGN_HEADERS = [
    'Date', 'Platform', 'Placement',
    'Campaign', 'Campaign ID',
    'Amount Spent', 'Impressions', 'Reach', 'Frequency', 'CPM',
    'Real Purchases', 'Purchases', 'Real CPT', 'Cost per Result',
    'Link Clicks', 'CTR (Link Click-Through)', 'CVR',
    'Purchase ROAS', 'Results Value',
]

PLATFORM_ADSET_HEADERS = [
    'Date', 'Platform', 'Placement',
    'Ad Set', 'Ad Set ID',
    'Campaign', 'Campaign ID',
    'Amount Spent', 'Impressions', 'Reach', 'Frequency', 'CPM',
    'Real Purchases', 'Purchases', 'Real CPT', 'Cost per Result',
    'Link Clicks', 'CTR (Link Click-Through)', 'CVR',
    'Purchase ROAS', 'Results Value',
]
