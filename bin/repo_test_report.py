"""Read native runner summaries, never infer passing tests from prose."""
import json,re
ANSI=re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
def summary(text):
 text=ANSI.sub('',text);lines=text.strip().splitlines()
 # Structured stdout from Jest/Vitest or Playwright JSON reporters.
 try:
  d=json.loads(text)
  if isinstance(d,dict) and all(type(d.get(k)) is int for k in ('numPassedTests','numFailedTests','numTotalTests')):
   return checked('Jest / Vitest JSON',d['numPassedTests'],d['numFailedTests'],d.get('numPendingTests',0)+d.get('numTodoTests',0),d['numTotalTests'])
  stats=d.get('stats',{}) if isinstance(d,dict) else {}
  if all(type(stats.get(k)) is int for k in ('expected','unexpected','skipped','flaky')):
   return checked('Playwright JSON',stats['expected'],stats['unexpected'],stats['skipped'],sum(stats[k] for k in ('expected','unexpected','skipped','flaky')),stats['flaky'])
 except (ValueError,TypeError):pass
 # TAP's final machine-readable counters (Node native test runner included).
 counters={m.group(1):int(m.group(2)) for line in lines[-35:] if (m:=re.fullmatch(r'#\s*(tests|pass|fail|skipped|todo)\s+(\d+)\s*',line.strip()))}
 if all(k in counters for k in ('tests','pass','fail')):
  return checked('TAP',counters['pass'],counters['fail'],counters.get('skipped',0)+counters.get('todo',0),counters['tests'])
 # Native Jest/Vitest Tests summary, not arbitrary "passed" log messages.
 for line in reversed(lines[-35:]):
  if not re.match(r'^\s*Tests\s*:?\s+\d+',line):continue
  counts={k:int(n) for n,k in re.findall(r'(\d+)\s+(passed|failed|skipped|todo|pending|total)',line)}
  if not any(k in counts for k in ('passed','failed')):continue
  total=counts.get('total');last=re.search(r'\((\d+)\)\s*$',line)
  if total is None and last:total=int(last.group(1))
  if total is not None:return checked('Jest / Vitest',counts.get('passed',0),counts.get('failed',0),sum(counts.get(k,0) for k in ('skipped','todo','pending')),total)
 return None

def checked(source,passed,failed,skipped,total,flaky=0):
 if any(type(x) is not int or x<0 for x in (passed,failed,skipped,total,flaky)) or passed+failed+skipped+flaky!=total:return None
 return dict(source=source,passed=passed,failed=failed,skipped=skipped,flaky=flaky,total=total)
