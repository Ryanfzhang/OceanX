"""Checks for the independent read-only trial; not OceanX runtime changes."""
import json
import unittest

from build_trial import HERE, METHODS, component, interval
from collect_run_measures import REMOTE


helpers = {}
exec(REMOTE.split('paths=json.loads(input())')[0], helpers)


def row(eid, signature, failed=True, agent='a'):
    return {'id': eid, 'agent': agent, 'failed': failed, 'signature': signature}


class TrialChecks(unittest.TestCase):
    def test_success_breaks_chain(self):
        stats = helpers['repeat_stats']([row('1','error'),row('2',None,False),row('3','error')])
        self.assertEqual(stats['repeated_failures'], 0)

    def test_agents_have_separate_previous_execution(self):
        stats = helpers['repeat_stats']([row('1','error'),row('2',None,False,'b'),row('3','error')])
        self.assertEqual(stats['repeated_failures'], 1)
        self.assertEqual(stats['pairs'][0]['previous'], '1')

    def test_missing_error_produces_bounds(self):
        stats = helpers['repeat_stats']([row('1',None),row('2','error'),row('3','error')])
        self.assertEqual(stats['repeated_failures'], 1)
        self.assertEqual(stats['ambiguous_pairs'], 1)
        self.assertLess(stats['score_lower'], stats['score'])

    def test_empty_executions_score_zero(self):
        self.assertEqual(helpers['repeat_stats']([])['score'], 0)

    def test_class_is_not_error_identity(self):
        stats=helpers['repeat_stats']([row('1',"NameError: name 'x' is not defined"),row('2',"NameError: name 'y' is not defined")])
        self.assertEqual(stats['repeated_failures'], 0)

    def test_error_display_normalization(self):
        self.assertEqual(helpers['signature']('header\\n\\u001b[31mValueError:  wrong   shape\\u001b[0m\\n'), 'ValueError: wrong shape')

    def test_notebook_output_error_not_later_stdout(self):
        text='### Output 2:\n```\nTraceback\nNameError: bad name\nprinted later\n```\n'
        self.assertEqual(helpers['nb_errors'](text)[0]['last_line'], 'NameError: bad name')

    def test_missing_parts_reallocate_to_judged(self):
        self.assertEqual(component(60)['combined'], 60)
        self.assertEqual(component(60,80)['combined'], 65)
        self.assertEqual(component(60,run=80)['combined'], 65)
        self.assertEqual(component(60,80,100)['combined'], 75)
        self.assertEqual(component(run=80)['combined'], 80)

    def test_paper_halves_preserve_grade(self):
        for level in range(5):
            self.assertEqual((min(level,2)/2+max(level-2,0)/2)/2,level/4)

    def test_rounded_equal_interval_not_duplicated(self):
        self.assertEqual(interval(74.413,74.414), '74.41')

    def test_saved_results_complete_and_reference_counts_absent(self):
        data=json.loads((HERE/'results.json').read_text())
        rows=data['attempts']
        self.assertEqual(len(rows),51)
        self.assertEqual(sum(r['type']=='open_problem' for r in rows),39)
        self.assertEqual(sum(r['type']=='paper_reproduction' for r in rows),12)
        for method in METHODS:
            self.assertEqual(sum(r['method']==method for r in rows),17)
        for r in rows:
            if r['type']=='open_problem':
                self.assertIsNone(r['counts']['answer_key'])
            else:
                self.assertTrue(all(x['matches_reference'] is None for x in r['counts']['findings']))
            self.assertAlmostEqual(r['original_criterion_total'],sum(c['weight']*c['level']/4 for c in r['original_criteria']))


if __name__ == '__main__':
    unittest.main()
