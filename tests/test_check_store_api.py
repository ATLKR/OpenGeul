import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from check_store_api import authenticate
from store_package import STORE_APP_ID


class StoreAuthenticationTests(unittest.TestCase):
    def test_shared_authentication_and_sanitized_failure(self):
        environment = {'STORE_APP_ID': STORE_APP_ID,
                       'STORE_TENANT_ID': '11111111-1111-1111-1111-111111111111',
                       'STORE_CLIENT_ID': '22222222-2222-2222-2222-222222222222',
                       'STORE_CLIENT_SECRET': 'test-private-value'}
        with patch.dict('os.environ', environment, clear=True), patch('urllib.request.build_opener') as factory:
            opener = factory.return_value
            opener.open.return_value = io.BytesIO(json.dumps({'access_token': 'test-token'}).encode())
            self.assertEqual(authenticate(), (opener, 'test-token'))
            self.assertEqual(opener.open.call_args.kwargs['timeout'], 30)
            opener.open.side_effect = urllib.error.HTTPError('https://example.test/test-private-value', 401,
                                                           'test-private-value', {}, None)
            with self.assertRaisesRegex(ValueError, 'OAuth failed with HTTP 401') as error:
                authenticate()
            self.assertNotIn('test-private-value', str(error.exception))


if __name__ == '__main__': unittest.main()
