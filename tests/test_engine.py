import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app  # noqa: E402


class EngineTests(unittest.TestCase):
    def test_python_execution(self):
        r = app.run_python("print(sum(map(int, input().split())))\n", "2 3 4\n")
        self.assertTrue(r.ok, r.stderr)
        self.assertEqual(app.normalize_output(r.stdout), "9")

    def test_round3_reference_python(self):
        code = """n=int(input())
a=list(map(int,input().split()))
u=sorted(set(a), reverse=True)
print(u[1] if len(u)>1 else 'NO')
"""
        r = app.evaluate_problem("r3_second_largest", "python", code, "submit")
        self.assertEqual(r["passed"], r["total"])

    def test_round2_even_sum_reference(self):
        code = """n=int(input())
a=list(map(int,input().split()))
print(sum(x for x in a if x%2==0))
"""
        r = app.evaluate_problem("r2_even_sum", "python", code, "submit")
        self.assertEqual(r["passed"], r["total"])

    def test_round2_vowel_reference(self):
        code = """s=input()
print(sum(ch.lower() in 'aeiou' for ch in s))
"""
        r = app.evaluate_problem("r2_count_vowels", "python", code, "submit")
        self.assertEqual(r["passed"], r["total"])

    def test_public_problem_hides_tests(self):
        p = app.public_problem(app.PROBLEMS["r3_second_largest"])
        self.assertNotIn("tests", p)
        self.assertIn("test_count", p)

    def test_round1_grade(self):
        payload = app.round1_payload("python")
        bank = app.all_round1_by_id()
        answers = {
            qid: bank[qid]["answer"]
            for qid in app.QUIZ_SESSIONS[payload["token"]]["question_ids"]
        }
        result = app.grade_round1(payload["token"], answers)
        self.assertEqual(result["percent"], 100.0)
        self.assertTrue(result["qualified"])

    @unittest.skipUnless(app.compiler_path(), "C++ compiler not available")
    def test_round3_reference_cpp(self):
        code = r'''#include <bits/stdc++.h>
using namespace std;
int main(){
    int n; if(!(cin>>n)) return 0;
    vector<long long> a(n); for(auto &x:a) cin>>x;
    set<long long> s(a.begin(),a.end());
    if(s.size()<2){ cout<<"NO\n"; return 0; }
    auto it=s.rbegin(); ++it; cout<<*it<<"\n";
    return 0;
}
'''
        r = app.evaluate_problem("r3_second_largest", "cpp", code, "submit")
        self.assertEqual(r["passed"], r["total"], r["results"])

    @unittest.skipUnless(app.compiler_path(), "C++ compiler not available")
    def test_round2_reference_cpp(self):
        code = r'''#include <bits/stdc++.h>
using namespace std;
int main(){
    int n; cin>>n;
    long long s=0,x;
    for(int i=0;i<n;i++){cin>>x;if(x%2==0)s+=x;}
    cout<<s<<"\n";
    return 0;
}
'''
        r = app.evaluate_problem("r2_even_sum", "cpp", code, "submit")
        self.assertEqual(r["passed"], r["total"], r["results"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
