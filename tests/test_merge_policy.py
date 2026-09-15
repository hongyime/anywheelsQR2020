"""Offline safety regressions; no credentials, GitHub calls or QR generation."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / '.github/scripts/checked-bot-merge.py'
SPEC = importlib.util.spec_from_file_location('merge_policy', SCRIPT)
policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(policy)

REPO = 'hongyime/anywheelsQR2020'
HEAD = 'a' * 40
ENDPOINT = f'repos/{REPO}/pulls/12'
ALLOWED = {'dependabot[bot]'}
BUILD = {'name': 'Build', 'workflow': 'Build Check', 'bucket': 'pass', 'state': 'SUCCESS'}


def pull_request():
    return {
        'state': 'open', 'draft': False, 'user': {'login': 'dependabot[bot]'},
        'head': {'sha': HEAD, 'repo': {'full_name': REPO}},
        'base': {'ref': 'master', 'repo': {'full_name': REPO, 'default_branch': 'master'}},
        'mergeable': True, 'mergeable_state': 'clean',
    }


class PolicyTests(unittest.TestCase):
    def setUp(self):
        # Every invocation must explicitly substitute a process result. If a
        # test misses a mock, fail before an external command can execute.
        self.process = patch.object(policy.subprocess, 'run', side_effect=AssertionError('No real subprocess'))
        self.process.start()
        self.addCleanup(self.process.stop)

    def test_eligible_pr_requires_both_build_results(self):
        self.assertIsNone(policy.decision(pull_request(), [BUILD], [BUILD], HEAD, ALLOWED))
        self.assertIsNotNone(policy.decision(pull_request(), [], [BUILD], HEAD, ALLOWED))
        self.assertIsNotNone(policy.decision(pull_request(), [BUILD], [], HEAD, ALLOWED))

    def test_untrusted_or_ineligible_metadata_is_refused(self):
        changes = [
            ('state', 'closed'), ('draft', True), ('user', {'login': 'human'}),
            ('mergeable', None), ('mergeable_state', 'blocked'),
            ('head', {'sha': 'b' * 40, 'repo': {'full_name': REPO}}),
            ('head', {'sha': HEAD, 'repo': {'full_name': 'someone/fork'}}),
            ('base', {'ref': 'main', 'repo': {'full_name': REPO, 'default_branch': 'master'}}),
        ]
        for field, value in changes:
            with self.subTest(field=field, value=value):
                pr = pull_request()
                pr[field] = value
                self.assertIsNotNone(policy.decision(pr, [BUILD], [BUILD], HEAD, ALLOWED))

    def test_failed_pending_or_wrong_workflow_never_passes(self):
        for change in ({'bucket': 'fail'}, {'bucket': 'pending'}, {'workflow': 'Impostor'}, {'state': 'PENDING'}):
            with self.subTest(change=change):
                changed = BUILD | change
                self.assertIsNotNone(policy.decision(pull_request(), [changed], [changed], HEAD, ALLOWED))
        self.assertIsNotNone(policy.decision(pull_request(), [BUILD], [BUILD, {'bucket': 'fail'}], HEAD, ALLOWED))

    def test_skipped_optional_check_does_not_replace_required_build(self):
        self.assertIsNone(policy.decision(pull_request(), [BUILD], [BUILD, {'bucket': 'skipping'}], HEAD, ALLOWED))
        self.assertIsNotNone(policy.decision(pull_request(), [BUILD | {'bucket': 'skipping'}], [BUILD], HEAD, ALLOWED))

    def test_dry_run_reads_again_without_merging(self):
        with patch.object(policy, 'gh', side_effect=[pull_request(), [BUILD], [BUILD], pull_request()]) as gh:
            self.assertIn('dry run', policy.inspect_and_merge(REPO, 12, ALLOWED, HEAD, True))
            self.assertEqual(gh.call_count, 4)
            self.assertEqual(gh.call_args.args, ('api', ENDPOINT))

    def test_exact_head_is_sent_to_merge_endpoint(self):
        with patch.object(policy, 'gh', side_effect=[pull_request(), [BUILD], [BUILD], pull_request(), {'merged': True}]) as gh:
            self.assertEqual(policy.inspect_and_merge(REPO, 12, ALLOWED), 'merged checked head')
            self.assertEqual(gh.call_args.args, ('api', '--method', 'PUT', ENDPOINT + '/merge', '-f', 'merge_method=squash', '-f', f'sha={HEAD}'))

    def test_head_change_during_checks_prevents_merge(self):
        latest = pull_request()
        latest['head']['sha'] = 'b' * 40
        with patch.object(policy, 'gh', side_effect=[pull_request(), [BUILD], [BUILD], latest]) as gh:
            self.assertEqual(policy.inspect_and_merge(REPO, 12, ALLOWED), 'PR head changed')
            self.assertEqual(gh.call_count, 4)

    def test_event_head_mismatch_stops_before_checks(self):
        with patch.object(policy, 'gh', return_value=pull_request()) as gh:
            self.assertEqual(policy.inspect_and_merge(REPO, 12, ALLOWED, 'b' * 40), 'PR head changed')
            self.assertEqual(gh.call_count, 1)

    def test_missing_required_checks_prevents_merge(self):
        with patch.object(policy, 'gh', side_effect=[pull_request(), [], [BUILD]]) as gh:
            self.assertIn('required Build', policy.inspect_and_merge(REPO, 12, ALLOWED))
            self.assertEqual(gh.call_count, 3)

    def test_repository_merge_refusal_is_preserved(self):
        with patch.object(policy, 'gh', side_effect=[pull_request(), [BUILD], [BUILD], pull_request(), {'merged': False}]):
            self.assertEqual(policy.inspect_and_merge(REPO, 12, ALLOWED), 'merge refused; PR left open')

    def test_only_expected_command_forms_are_allowed(self):
        forms = [
            (('api', ENDPOINT), False),
            (('api', '--paginate', '--slurp', f'repos/{REPO}/pulls?state=open&per_page=100'), False),
            (('pr', 'checks', '12', '--repo', REPO, '--json', policy.CHECK_FIELDS), True),
            (('pr', 'checks', '12', '--repo', REPO, '--required', '--json', policy.CHECK_FIELDS), True),
            (('api', '--method', 'PUT', ENDPOINT + '/merge', '-f', 'merge_method=squash', '-f', f'sha={HEAD}'), False),
        ]
        for args, checks in forms:
            with self.subTest(args=args):
                self.assertTrue(policy.allowed_command(args, checks))

    def test_malformed_or_expanded_commands_are_rejected_before_execution(self):
        forms = [
            (), ('api', '--help'), ('pr', 'merge', '12', '--admin'),
            ('api', ENDPOINT, '--jq', 'anything'),
            ('api', 'repos/../repo/pulls/12'), ('api', ENDPOINT + ';echo unsafe'),
            ('api', '--method', 'DELETE', ENDPOINT),
            ('api', '--method', 'PUT', ENDPOINT + '/merge', '-f', 'merge_method=squash', '-f', 'sha=bad'),
            ('pr', 'checks', '-1', '--repo', REPO, '--json', policy.CHECK_FIELDS),
        ]
        for args in forms:
            with self.subTest(args=args), self.assertRaises(ValueError):
                policy.gh(*args)

    def test_absolute_cli_no_shell_and_timeout(self):
        executable = str(Path('gh-test.exe').resolve())
        with patch.object(policy.shutil, 'which', return_value=executable), patch.object(policy.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='{}')) as run:
            self.assertEqual(policy.gh('api', ENDPOINT), {})
            self.assertEqual(run.call_args.args[0], [executable, 'api', ENDPOINT])
            self.assertIs(run.call_args.kwargs['shell'], False)
            self.assertEqual(run.call_args.kwargs['timeout'], 45)

    def test_missing_or_relative_cli_is_refused(self):
        for executable in (None, 'relative/gh'):
            with self.subTest(executable=executable), patch.object(policy.shutil, 'which', return_value=executable), self.assertRaises(RuntimeError):
                policy.gh('api', ENDPOINT)

    def test_check_exit_codes_return_json_for_policy_evaluation(self):
        executable = str(Path('gh-test.exe').resolve())
        for code in (0, 1, 8):
            with self.subTest(code=code), patch.object(policy.shutil, 'which', return_value=executable), patch.object(policy.subprocess, 'run', return_value=SimpleNamespace(returncode=code, stdout='[]')):
                self.assertEqual(policy.gh('pr', 'checks', '12', '--repo', REPO, '--json', policy.CHECK_FIELDS, checks=True), [])

    def test_api_failure_and_malformed_json_are_not_accepted(self):
        executable = str(Path('gh-test.exe').resolve())
        for code, output, error in ((1, '{}', RuntimeError), (8, '[]', RuntimeError), (0, 'invalid', ValueError)):
            with self.subTest(code=code, output=output), patch.object(policy.shutil, 'which', return_value=executable), patch.object(policy.subprocess, 'run', return_value=SimpleNamespace(returncode=code, stdout=output)), self.assertRaises(error):
                policy.gh('api', ENDPOINT)


if __name__ == '__main__':
    unittest.main()
