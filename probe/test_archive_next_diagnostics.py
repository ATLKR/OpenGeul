"""실패 원인은 분류하되 비밀값·원문·외부 traceback은 남기지 않는다."""
import json
import unittest
import archive_next as subject


class FailureDiagnosticsTests(unittest.TestCase):
    def test_local_frames_identify_guard_without_exception_message(self):
        secret = 'Bearer private-token https://example.invalid/?signature=secret'
        try:
            subject.require(False)
        except ValueError as error:
            error.args = (secret,)
            details = subject.failure_details(error)
        self.assertEqual(details['exceptionType'], 'ValueError')
        self.assertEqual([frame['function'] for frame in details['frames']], ['require'])
        self.assertTrue(all(type(frame['line']) is int for frame in details['frames']))
        self.assertNotIn(secret, json.dumps(details))
        self.assertNotIn(__file__, json.dumps(details))

    def test_unknown_exception_type_and_external_frame_are_redacted(self):
        class PrivateTokenException(Exception):
            pass
        try:
            raise PrivateTokenException('private-token')
        except Exception as error:
            details = subject.failure_details(error)
        self.assertEqual(details, {'exceptionType': 'Exception', 'frames': []})

    def test_input_shapes_and_environment_are_only_controlled_flags(self):
        for value, expected in [(None, 'null'), ({}, 'empty_object'),
                                ({'private-token': 'secret'}, 'nonempty_object'),
                                ('private-token', 'other')]:
            details = subject.context_diagnostics({'GH_TOKEN': 'private-token'},
                {'repository': {'full_name': 'private-token', 'private': True}, 'inputs': value})
            self.assertEqual(details['inputsShape'], expected)
            self.assertFalse(details['repositoryMatches'])
            self.assertFalse(details['repositoryPublic'])
            self.assertNotIn('private-token', json.dumps(details))
            self.assertTrue(all(type(value) is bool for value in details['environmentMatches'].values()))
        self.assertEqual(subject.context_diagnostics({}, {})['inputsShape'], 'missing')

    def test_reporting_does_not_accept_null_inputs_or_wrong_context(self):
        env = {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted',
            'GITHUB_REPOSITORY': 'ATLKR/OpenGeul', 'GITHUB_ACTOR': 'ATLKR',
            'GITHUB_TRIGGERING_ACTOR': 'ATLKR', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
            'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_REF': 'refs/heads/diagnostic/archive-next-conditional',
            'GITHUB_WORKFLOW_REF': 'ATLKR/OpenGeul/.github/workflows/store-package.yml@refs/heads/diagnostic/archive-next-conditional',
            'GITHUB_RUN_ID': '123', 'GH_TOKEN': 'same', 'GITHUB_TOKEN': 'same'}
        event = {'repository': {'full_name': 'ATLKR/OpenGeul', 'private': False}, 'inputs': None}
        self.assertEqual(subject.context_diagnostics(env, event)['inputsShape'], 'null')
        with self.assertRaises(ValueError):
            subject.context(env, event)


if __name__ == '__main__':
    unittest.main()
