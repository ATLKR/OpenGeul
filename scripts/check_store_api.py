"""Validate Store credentials with OAuth and one read-only application lookup."""
from __future__ import annotations
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

from store_package import STORE_APP_ID, STORE_IDENTITY
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ci'))
from transport_cleanup import NoRedirect


def main():
    stage='configuration'
    try:
        tenant=str(uuid.UUID(os.environ['STORE_TENANT_ID']))
        client=str(uuid.UUID(os.environ['STORE_CLIENT_ID']))
        secret=os.environ['STORE_CLIENT_SECRET']
        if not secret or os.environ.get('STORE_APP_ID')!=STORE_APP_ID:
            raise ValueError('Store configuration does not match the reserved app')
        opener=urllib.request.build_opener(NoRedirect())
        body=urllib.parse.urlencode({'grant_type':'client_credentials','client_id':client,
                                    'client_secret':secret,'scope':'https://manage.devcenter.microsoft.com/.default'}).encode()
        stage='OAuth'
        request=urllib.request.Request(f'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token',data=body,
                                       headers={'Content-Type':'application/x-www-form-urlencoded'})
        with opener.open(request,timeout=30) as response:
            token=json.load(response).get('access_token')
        if not isinstance(token,str) or not token: raise ValueError('OAuth returned no access token')
        print('OAuth authentication succeeded; checking Store application read access.')
        stage='Store application GET'
        request=urllib.request.Request(f'https://manage.devcenter.microsoft.com/v1.0/my/applications/{STORE_APP_ID}',
                                       headers={'Authorization':'Bearer '+token,'Accept':'application/json'},method='GET')
        with opener.open(request,timeout=30) as response: app=json.load(response)
        if app.get('id')!=STORE_APP_ID or app.get('packageIdentityName')!=STORE_IDENTITY['name']:
            raise ValueError('Store application lookup returned a different app')
    except urllib.error.HTTPError as error:
        raise SystemExit(f'{stage} failed with HTTP {error.code}; credentials and response contents were not logged.') from None
    except (KeyError,ValueError,urllib.error.URLError,TimeoutError):
        raise SystemExit(f'{stage} failed; check configured credentials and app access. Credentials and response contents were not logged.') from None
    print(f'Read-only Store API access verified for OpenGeul ({STORE_APP_ID}).')


if __name__=='__main__': main()
