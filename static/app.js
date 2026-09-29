'use strict';



const $ = (selector, root = document) => root.querySelector(selector);

const $$ = (selector, root = document) =>

  [...root.querySelectorAll(selector)];



const state = {

  config: null,

  capabilities: null,

  participant: '',

  collegeId: '',

  language: 'python',

  round: 0,

  timerId: null,

  secondsLeft: 0,

  round1Token: null,

  round1Questions: [],

  round1Result: null,

  round2Problems: [],

  round3Problems: [],

  editorCache: {},

  completed: false,

};



const privateReceipts = {

  2: {},

  3: {},

};



let adminPassword = '';

let busy = false;

let loadingRound = false;

let tabResetTriggered = false;



// ---------- General helpers ----------



async function api(path, options = {}) {

  const response = await fetch(path, {

    ...options,

    cache: 'no-store',

    headers: {

      'Content-Type': 'application/json',

      ...(options.headers || {}),

    },

  });



  const type = response.headers.get('content-type') || '';

  const data = type.includes('application/json')

    ? await response.json()

    : await response.text();



  // Ignore old requests while a tab-switch reset is navigating away.

  if (tabResetTriggered) return new Promise(() => {});



  if (!response.ok) {

    throw new Error(data.error || data || `HTTP ${response.status}`);

  }



  return data;

}



function escapeHtml(value) {

  return String(value ?? '').replace(/[&<>'"]/g, character => ({

    '&': '&amp;',

    '<': '&lt;',

    '>': '&gt;',

    "'": '&#39;',

    '"': '&quot;',

  }[character]));

}



function toast(message, kind = '') {

  const element = document.createElement('div');

  element.className = `toast ${kind}`;

  element.textContent = message;

  document.body.appendChild(element);

  setTimeout(() => element.remove(), 5000);

}



function isQuizActive() {

  return state.round >= 1 && state.round <= 3;

}



function updateAdminButton() {

  const button = $('#adminBtn');

  const visible = location.hash === '#admin' && !isQuizActive();

  button.hidden = !visible;

  button.style.display = visible ? '' : 'none';

}



function setSteps(round) {

  $$('.step').forEach((element, index) => {

    const number = index + 1;

    element.classList.toggle('active', number === round);

    element.classList.toggle('done', number < round);

  });

}



function stopTimer() {

  clearInterval(state.timerId);

  state.timerId = null;

}



function startTimer(minutes, onExpire) {

  stopTimer();



  const duration = Math.max(1, Number(minutes) || 1) * 60;

  const deadline = Date.now() + duration * 1000;



  const update = () => {

    state.secondsLeft = Math.max(

      0,

      Math.ceil((deadline - Date.now()) / 1000)

    );



    const minutesLeft = Math.floor(state.secondsLeft / 60);

    const seconds = state.secondsLeft % 60;



    $('#timer').textContent =

      `${String(minutesLeft).padStart(2, '0')}:` +

      `${String(seconds).padStart(2, '0')}`;



    $('#timer').style.color =

      state.secondsLeft <= 60 ? 'var(--warn)' : '';



    if (state.secondsLeft === 0) {

      stopTimer();

      onExpire();

    }

  };



  state.timerId = setInterval(update, 250);

  update();

}



function requireReceipt(result) {

  if (!result || typeof result.receipt !== 'string') {

    throw new Error(

      'The server is using the old grading code. ' +

      'Ask the organizer to update app.py and restart it.'

    );

  }



  return result.receipt;

}



function editorKey(problemId) {

  return `${problemId}:${state.language}`;

}



function saveCurrentEditor() {

  const editor = $('#codeEditor');



  if (editor?.dataset.problem) {

    state.editorCache[editorKey(editor.dataset.problem)] = editor.value;

  }

}



// ---------- Branding and startup ----------



function applyEditableBranding(config) {

  const branding = config.branding || {};



  for (const [name, value] of Object.entries(config.theme || {})) {

    if (name.startsWith('--') && typeof value === 'string') {

      document.documentElement.style.setProperty(name, value);

    }

  }



  document.title = branding.title || config.title || document.title;



  const labels = {

    '#brandEyebrow': branding.header_eyebrow,

    '#brandTitle': branding.header_title,

    '#heroBadge': branding.hero_badge,

    '#heroTitle': branding.hero_title,

    '#heroDescription': branding.hero_description,

    '#participantLabel': branding.participant_label,

    '#collegeIdLabel': branding.college_id_label,

    '#languageLabel': branding.language_label,

    '#startButton': branding.start_button,

  };



  for (const [selector, value] of Object.entries(labels)) {

    const element = $(selector);

    if (element && typeof value === 'string' && value.trim()) {

      element.textContent = value;

    }

  }



  for (const [selector, source] of [

    ['#leftLogo', branding.left_logo],

    ['#rightLogo', branding.right_logo],

  ]) {

    const image = $(selector);



    if (image && typeof source === 'string' && source.trim()) {

      image.src = source.trim();

      image.classList.remove('hidden');

      image.onerror = () => image.classList.add('hidden');

    }

  }



  $('#adminBtn').textContent = 'Admin Results';

}



async function init() {

  $('#startButton').disabled = true;

  updateAdminButton();



  try {

    const data = await api('/api/config');



    state.config = data.config;

    state.capabilities = data.capabilities;

    applyEditableBranding(state.config);



    const cppAvailable = Boolean(data.capabilities.cpp?.available);



    $('#connectionBadge').textContent =

      `Python ready · C++ ${cppAvailable ? 'ready' : 'compiler missing'}`;



    const cppOption = $('#language option[value="cpp"]');



    if (cppOption) {

      cppOption.disabled = !cppAvailable;

      cppOption.textContent = cppAvailable

        ? 'C++'

        : 'C++ (compiler not detected)';

    }



    if (!cppAvailable && $('#language').value === 'cpp') {

      $('#language').value = 'python';

    }



    $('#startButton').disabled = false;

  } catch (error) {

    $('#connectionBadge').textContent = 'Engine unavailable';

    toast(error.message, 'error');

  }

}



$('#startForm').addEventListener('submit', async event => {

  event.preventDefault();



  if (!state.config || busy || isQuizActive()) return;



  state.participant = $('#participant').value.trim();

  state.collegeId = $('#collegeId').value.trim();

  state.language = $('#language').value;



  if (!state.participant) {

    toast('Enter your name.', 'error');

    return;

  }



  if (

    state.language === 'cpp' &&

    !state.capabilities.cpp?.available

  ) {

    toast('The server does not have a C++ compiler yet.', 'error');

    return;

  }



  busy = true;

  $('#startButton').disabled = true;

  $('#welcome').classList.add('hidden');

  $('#adminPanel').classList.add('hidden');

  $('#competition').classList.remove('hidden');



  try {

    await startRound1();

  } catch (error) {

    state.round = 0;

    document.body.classList.remove('quiz-active');

    $('#competition').classList.add('hidden');

    $('#welcome').classList.remove('hidden');

    updateAdminButton();

    toast(error.message, 'error');

  } finally {

    busy = false;

    $('#startButton').disabled = false;

  }

});



// ---------- Round 1 ----------



async function startRound1() {

  state.round = 1;

  document.body.classList.add('quiz-active');

  updateAdminButton();

  setSteps(1);



  $('#roundPanel').textContent = 'Loading Round 1…';



  const data = await api(

    `/api/round1?language=${encodeURIComponent(state.language)}`

  );



  state.round1Token = data.token;

  state.round1Questions = data.questions;



  $('#roundPanel').innerHTML = `

    <div class="section-head">

      <div>

        <span class="round-pill">ROUND 1</span>

        <h2>Coding Aptitude & MCQ</h2>

        <p class="muted">

          Select your answers and submit to continue.

        </p>

      </div>

      <div class="score-card">${data.questions.length} questions</div>

    </div>



    <form id="round1Form">

      ${data.questions.map((question, index) => `

        <div class="question">

          <div class="qtext">

            ${index + 1}. ${escapeHtml(question.question)}

          </div>

          <div class="options">

            ${question.options.map((option, optionIndex) => `

              <label class="option">

                <input

                  type="radio"

                  name="question_${index}"

                  value="${optionIndex}"

                >

                <span>${escapeHtml(option)}</span>

              </label>

            `).join('')}

          </div>

        </div>

      `).join('')}



      <div class="nav-row">

        <button class="primary" type="submit">

          Submit Round 1

        </button>

      </div>

    </form>

  `;



  $('#round1Form').addEventListener('submit', submitRound1);



  startTimer(

    state.config.round1_minutes,

    () => submitRound1(null, true)

  );

}



async function submitRound1(event, timedOut = false) {

  if (event) event.preventDefault();

  if (busy) return;



  const form = $('#round1Form');

  if (!form) return;



  const answers = {};



  state.round1Questions.forEach((question, index) => {

    const selected = $(

      `input[name="question_${index}"]:checked`,

      form

    );



    if (selected) answers[question.id] = Number(selected.value);

  });



  if (

    !timedOut &&

    Object.keys(answers).length < state.round1Questions.length &&

    !confirm('Some questions are unanswered. Submit anyway?')

  ) {

    return;

  }



  busy = true;

  stopTimer();

  $$('input, button', form).forEach(element => {

    element.disabled = true;

  });



  try {

    const result = await api('/api/round1/grade', {

      method: 'POST',

      body: JSON.stringify({

        token: state.round1Token,

        answers,

      }),

    });



    requireReceipt(result);

    state.round1Result = result;



    await renderRound1Result();

  } catch (error) {

    toast(error.message, 'error');



    // Keep answers locked after submission; allow a retry.

    const button = $('button[type="submit"]', form);

    if (button) {

      button.disabled = false;

      button.textContent = 'Retry submission';

    }

  } finally {

    busy = false;

  }

}



// No answers or marks are displayed.

function renderRound1Result() {

  return transitionToRound(2);

}



// ---------- Round transitions ----------



async function transitionToRound(roundNo) {

  if (loadingRound) return;

  loadingRound = true;



  $('#roundPanel').innerHTML = `

    <h2>Round ${roundNo - 1} submitted.</h2>

    <p id="transitionMessage">Opening Round ${roundNo}…</p>

    <button id="retryRound" class="primary" disabled>

      Continue to Round ${roundNo}

    </button>

  `;



  $('#retryRound').addEventListener('click', () => {

    transitionToRound(roundNo);

  });



  try {

    if (roundNo === 2) await startRound2();

    else await startRound3();

  } catch (error) {

    $('#transitionMessage').textContent =

      'Could not load the next round. Click Continue to retry.';

    $('#retryRound').disabled = false;

    toast(error.message, 'error');

  } finally {

    loadingRound = false;

  }

}



function startRound2() {

  return startCodingRound(2);

}



function startRound3() {

  return startCodingRound(3);

}



async function startCodingRound(roundNo) {

  const data = await api(`/api/problems?round=${roundNo}&language=${encodeURIComponent(state.language)}`);



  if (!Array.isArray(data.problems) || !data.problems.length) {

    throw new Error(`No problems configured for Round ${roundNo}.`);

  }



  state.round = roundNo;



  if (roundNo === 2) state.round2Problems = data.problems;

  else state.round3Problems = data.problems;



  setSteps(roundNo);

  renderCodingRound(roundNo, data.problems);



  startTimer(

    state.config[`round${roundNo}_minutes`],

    () => roundNo === 2 ? finishRound2() : finishRound3()

  );

}



// ---------- Coding interface ----------



function renderCodingRound(roundNo, problems) {
  $('#roundPanel').innerHTML = `
    <div class="section-head">
      <div>
        <span class="round-pill">ROUND ${roundNo}</span>
        <h2>
          ${roundNo === 2
            ? 'Debugging & Problem Solving'
            : 'Test Case Challenge'}
        </h2>
        <p class="muted">
          Complete the tasks. Results are visible only to organizers.
        </p>
      </div>

      <div class="score-card">
        Language: ${state.language === 'python' ? 'Python' : 'C++'}
      </div>
    </div>

    <div class="problem-tabs">
      ${problems.map((problem, index) => `
        <button
          class="problem-tab ${index === 0 ? 'active' : ''}"
          data-index="${index}"
        >${escapeHtml(problem.title)}</button>
      `).join('')}
    </div>

    <div id="problemHost"></div>
  `;

  $$('.problem-tab').forEach(button => {
    button.addEventListener('click', () => {
      if (busy) return;

      saveCurrentEditor();

      $$('.problem-tab').forEach(tab => {
        tab.classList.remove('active');
      });

      button.classList.add('active');

      const index = Number(button.dataset.index);

      showProblem(
        problems[index],
        roundNo,
        index,
        problems
      );
    });
  });

  showProblem(problems[0], roundNo, 0, problems);
}


function activateProblemTab(index) {
  $$('.problem-tab').forEach((tab, tabIndex) => {
    tab.classList.toggle('active', tabIndex === index);
  });
}


function showProblem(problem, roundNo, currentIndex, problems) {
  const key = editorKey(problem.id);

  const code =
    state.editorCache[key] ?? problem.starter[state.language];

  state.editorCache[key] = code;

  const isFirst = currentIndex === 0;
  const isLast = currentIndex === problems.length - 1;

  $('#problemHost').innerHTML = `
    <div class="problem-layout">
      <div class="problem-card">
        <div class="eyebrow">
          ${escapeHtml(String(problem.kind || '').toUpperCase())}
        </div>

        <p class="small muted">
          Question ${currentIndex + 1} of ${problems.length}
        </p>

        <h3>${escapeHtml(problem.title)}</h3>
        <p>${escapeHtml(problem.statement)}</p>

        <h4>Input</h4>
        <p>${escapeHtml(problem.input_format)}</p>

        <h4>Output</h4>
        <p>${escapeHtml(problem.output_format)}</p>

        <h4>Examples</h4>

        ${(problem.samples || []).map(sample => `
          <div class="sample">Input:
${escapeHtml(sample.input)}

Output:
${escapeHtml(sample.output)}</div>
        `).join('<br>')}
      </div>

      <div class="editor-card">
        <div class="editor-toolbar">
          <strong>Code editor</strong>

          <div class="actions">
            <button id="resetCode" class="ghost">
              Reset code
            </button>
          </div>
        </div>

        <textarea
          id="codeEditor"
          class="editor"
          spellcheck="false"
          data-problem="${escapeHtml(problem.id)}"
        >${escapeHtml(code)}</textarea>

        <div class="nav-row">
          <button id="runCode" class="primary">
            Run Code
          </button>
        </div>

        <div id="console" class="console">
          Edit the code, then click Run Code to see the output.
        </div>

        <div class="nav-row">
          ${!isFirst
            ? '<button id="previousQuestion" class="ghost">Previous Question</button>'
            : ''}

          ${!isLast
            ? '<button id="nextQuestion" class="primary">Next Question</button>'
            : `<button id="finishCodingRound" class="primary">${
                roundNo === 2
                  ? 'Finish Round 2 & Continue to Round 3'
                  : 'Submit Final Round'
              }</button>`}
        </div>
      </div>
    </div>
  `;

  const editor = $('#codeEditor');

  editor.addEventListener('input', () => {
    state.editorCache[key] = editor.value;
  });

  editor.addEventListener('keydown', event => {
    if (event.key !== 'Tab') return;

    event.preventDefault();

    const start = editor.selectionStart;
    const end = editor.selectionEnd;

    editor.value =
      editor.value.slice(0, start) +
      '    ' +
      editor.value.slice(end);

    editor.selectionStart = editor.selectionEnd = start + 4;
    state.editorCache[key] = editor.value;
  });

  $('#resetCode').addEventListener('click', () => {
    if (busy || editor.disabled) return;

    if (!confirm('Restore the starter code for this problem?')) {
      return;
    }

    editor.value = problem.starter[state.language];
    state.editorCache[key] = editor.value;
    $('#console').textContent = 'Starter code restored.';
  });

  $('#runCode').addEventListener('click', async () => {
    if (busy || editor.disabled) return;

    saveCurrentEditor();

    const runButton = $('#runCode');

    runButton.disabled = true;
    runButton.textContent = 'Running…';

    $('#console').textContent = 'Running code…';

    try {
      const result = await evaluate(
        problem,
        'sample',
        roundNo
      );

      if (!Array.isArray(result.results)) {
        throw new Error(
          'Run Code requires the sample-run backend change in app.py.'
        );
      }

      const output = result.results.map(test => {
        if (test.compile_error) {
          return `Compilation error:
${test.stderr || ''}`;
        }

        if (test.timed_out) {
          return `Sample ${test.test}: TIME LIMIT`;
        }

        const lines = [
          `Sample ${test.test}: ${test.passed ? 'PASS' : 'FAIL'}`,
          `Expected: ${test.expected}`,
          `Your output: ${test.actual || '(no output)'}`,
        ];

        if (test.stderr) {
          lines.push(`Error: ${test.stderr}`);
        }

        return lines.join('\n');
      });

      $('#console').textContent =
        output.join('\n\n') ||
        'Program finished with no output.';
    } catch (error) {
      $('#console').textContent =
        `Error: ${error.message}`;

      toast(error.message, 'error');
    } finally {
      if (runButton?.isConnected) {
        runButton.disabled = false;
        runButton.textContent = 'Run Code';
      }
    }
  });

  $('#previousQuestion')?.addEventListener('click', () => {
    if (busy) return;

    saveCurrentEditor();

    const previousIndex = currentIndex - 1;

    activateProblemTab(previousIndex);

    showProblem(
      problems[previousIndex],
      roundNo,
      previousIndex,
      problems
    );
  });

  $('#nextQuestion')?.addEventListener('click', () => {
    if (busy) return;

    saveCurrentEditor();

    const nextIndex = currentIndex + 1;

    activateProblemTab(nextIndex);

    showProblem(
      problems[nextIndex],
      roundNo,
      nextIndex,
      problems
    );
  });

  $('#finishCodingRound')?.addEventListener('click', () => {
    if (roundNo === 2) {
      finishRound2();
    } else {
      finishRound3();
    }
  });
}


// ---------- Private grading and final submission ----------



async function evaluate(problem, mode, roundNo) {
  const code =
    state.editorCache[editorKey(problem.id)] ??
    problem.starter[state.language];

  const result = await api('/api/evaluate', {
    method: 'POST',
    body: JSON.stringify({
      problem_id: problem.id,
      language: state.language,
      code,
      mode,
    }),
  });

  if (mode === 'sample') {
    return result;
  }

  privateReceipts[roundNo][problem.id] = requireReceipt(result);
  return result;
}


function finishRound2() {

  return finishCodingRound(2);

}



function finishRound3() {

  return finishCodingRound(3);

}



async function finishCodingRound(roundNo) {

  if (busy || state.round !== roundNo) return;



  busy = true;

  stopTimer();

  saveCurrentEditor();



  const problems = roundNo === 2

    ? state.round2Problems

    : state.round3Problems;



  const finishButton = $('#finishCodingRound');



  // Freeze the submitted code, including when a retry is needed.

  $$('button, textarea', $('#roundPanel')).forEach(element => {

    element.disabled = true;

  });



  if ($('#console')) {

    $('#console').textContent = 'Submitting this round. Please wait…';

  }



  try {

    for (const problem of problems) {

      // Reuse successful receipts if a later request failed.

      if (!privateReceipts[roundNo][problem.id]) {

        await evaluate(problem, 'submit', roundNo);

      }

    }



    if (roundNo === 2) await transitionToRound(3);

    else await showFinal();

  } catch (error) {

    toast(error.message, 'error');



    if ($('#console')) {

      $('#console').textContent =

        'Submission could not be completed. Click Retry submission.';

    }



    if (finishButton?.isConnected) {

      finishButton.disabled = false;

      finishButton.textContent = 'Retry submission';

    }

  } finally {

    busy = false;

  }

}



async function showFinal() {

  const saved = await api('/api/results', {

    method: 'POST',

    body: JSON.stringify({

      participant: state.participant,

      college_id: state.collegeId,

      language: state.language,

      round1_receipt: state.round1Result.receipt,

      round2_receipts: privateReceipts[2],

      round3_receipts: privateReceipts[3],

    }),

  });



  if (!saved.saved) {

    throw new Error('The server did not confirm your submission.');

  }



  stopTimer();

  state.round = 0;

  state.completed = true;

  document.body.classList.remove('quiz-active');

  setSteps(4);

  updateAdminButton();



  $('#roundPanel').innerHTML = `

    <div class="result-banner ok">

      <h2>Submitted successfully!</h2>

      <p>Thank you, ${escapeHtml(state.participant)}.</p>

      <p>You have completed all three rounds.</p>

      <p>Results will be announced by the organizers.</p>

      <p class="small muted">

        Submission ID: ${escapeHtml(saved.id)}

      </p>

    </div>

  `;

}



// ---------- Admin results ----------



window.addEventListener('hashchange', updateAdminButton);



$('#adminBtn').addEventListener('click', async () => {

  if (isQuizActive()) return;



  const entered = prompt(

    'Enter the admin password shown in the server terminal:'

  );



  if (!entered) return;



  try {

    const data = await api('/api/results', {

      headers: {

        'X-Admin-Password': entered,

      },

    });



    adminPassword = entered;

    const rows = data.results || [];



    $('#resultsTable').innerHTML = rows.length

    
      ? `

        <table class="results-table">

          <thead>

            <tr>

              <th>Saved</th>

              <th>Participant</th>

              <th>ID</th>

              <th>Language</th>

              <th>Round 1</th>

              <th>Round 2</th>

              <th>Round 3</th>

            </tr>

          </thead>

          <tbody>

            ${rows.map(row => `

              <tr>

                <td>${escapeHtml(row.saved_at)}</td>

                <td>${escapeHtml(row.participant)}</td>

                <td>${escapeHtml(row.college_id)}</td>

                <td>${escapeHtml(row.language)}</td>

                <td>${escapeHtml(row.round1?.percent ?? '-')}%</td>

                <td>${escapeHtml(row.round2?.percent ?? '-')}%</td>

                <td>

                  ${escapeHtml(row.round3?.passed ?? '-')} /

                  ${escapeHtml(row.round3?.total ?? '-')}

                </td>

              </tr>

            `).join('')}

          </tbody>

        </table>

      `

      : '<p class="muted">No saved attempts yet.</p>';



    $('#welcome').classList.add('hidden');

    $('#competition').classList.add('hidden');

    $('#adminPanel').classList.remove('hidden');

  } catch (error) {

    adminPassword = '';

    toast(error.message, 'error');

  }

});



$('#closeAdmin').addEventListener('click', () => {

  adminPassword = '';

  $('#resultsTable').innerHTML = '';

  $('#adminPanel').classList.add('hidden');



  if (isQuizActive() || state.completed) {

    $('#competition').classList.remove('hidden');

  } else {

    $('#welcome').classList.remove('hidden');

  }

});



$('a[href="/api/results.csv"]')?.addEventListener(

  'click',

  async event => {

    event.preventDefault();



    if (!adminPassword) {

      toast('Open Admin Results and enter the password first.', 'error');

      return;

    }



    try {

      const response = await fetch('/api/results.csv', {

        headers: {

          'X-Admin-Password': adminPassword,

        },

        cache: 'no-store',

      });



      if (!response.ok) {

        throw new Error('Admin access denied. Open Admin Results again.');

      }



      const blob = await response.blob();

      const url = URL.createObjectURL(blob);

      const link = document.createElement('a');



      link.href = url;

      link.download = 'Code_Rookie_Results.csv';

      document.body.appendChild(link);

      link.click();

      link.remove();



      setTimeout(() => URL.revokeObjectURL(url), 1000);

    } catch (error) {

      toast(error.message, 'error');

    }

  }

);



// ---------- Anti-copy and tab-switch reset ----------



const protectionStyle = document.createElement('style');

protectionStyle.textContent = `

  body.quiz-active #competition {

    -webkit-user-select: none;

    user-select: none;

    -webkit-touch-callout: none;

  }



  body.quiz-active #competition textarea,

  body.quiz-active #competition input {

    -webkit-user-select: text;

    user-select: text;

  }



  @media print {

    body.quiz-active #competition {

      display: none !important;

    }

  }

`;

document.head.appendChild(protectionStyle);



for (const eventName of ['copy', 'cut', 'contextmenu', 'dragstart']) {

  document.addEventListener(eventName, event => {

    if (isQuizActive()) event.preventDefault();

  }, true);

}



document.addEventListener('selectstart', event => {

  if (!isQuizActive()) return;



  if (!event.target.closest?.('textarea, input')) {

    event.preventDefault();

  }

}, true);



document.addEventListener('keydown', event => {

  if (!isQuizActive()) return;



  const key = event.key.toLowerCase();



  const blocked =

    ((event.ctrlKey || event.metaKey) &&

      ['c', 'x', 'p', 's'].includes(key)) ||

    (event.ctrlKey && event.key === 'Insert') ||

    (event.shiftKey && event.key === 'Delete');



  if (blocked) event.preventDefault();

}, true);



document.addEventListener('visibilitychange', () => {

  if (!document.hidden || !isQuizActive() || tabResetTriggered) return;



  tabResetTriggered = true;

  stopTimer();



  try {

    sessionStorage.setItem('quizTabReset', 'yes');

  } catch (_) {}



  window.location.reload();

});



function showTabResetMessage() {

  if (document.hidden) return;



  try {

    if (sessionStorage.getItem('quizTabReset') === 'yes') {

      sessionStorage.removeItem('quizTabReset');



      alert(

        'You left the quiz tab. Your answers and code were cleared. ' +

        'Start again from Round 1.'

      );

    }

  } catch (_) {}

}



document.addEventListener('visibilitychange', showTabResetMessage);



// Add the rule notice if it is not already in the HTML.

if (!$('#startForm').textContent.includes('Switching tabs')) {

  const notice = document.createElement('p');

  notice.className = 'result-banner bad';

  notice.textContent =

    'Quiz rules: Copying questions is blocked. Switching tabs, ' +

    'minimizing the browser or switching apps clears your attempt. ' +

    'You must then start again from Round 1.';



  $('#startButton').before(notice);

}



showTabResetMessage();

init();