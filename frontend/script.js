const API = (path) => (window.API_BASE_URL || 'http://localhost:8000') + path;
let sessionId = null;
let currentQuestion = null;
let selectedOptionId = null;
let score = { correct: 0, total: 0 };
let mode = 'submit';

const statusEl = document.getElementById('status');
const scoreEl = document.getElementById('score');
const cardEl = document.getElementById('card');
const questionEl = document.getElementById('question');
const optionsEl = document.getElementById('options');
const nextBtn = document.getElementById('nextBtn');
const overlay = document.getElementById('overlay');
const overlayContent = document.getElementById('overlayContent');

function setStatus(text){ statusEl.textContent = text; }
function showCard(){ cardEl.classList.remove('hidden'); }
function showOverlay(message, variant='info'){ overlayContent.textContent = message; overlayContent.className = `overlay-content ${variant}`; overlay.classList.remove('hidden'); setTimeout(()=>overlay.classList.add('hidden'), 700); }
function updateScore(){ scoreEl.textContent = `Score: ${score.correct} / ${score.total}`; }

async function startSession(){
	setStatus('Starting session...');
	const res = await fetch(API('/api/session/start'), { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({}) });
	const data = await res.json();
	sessionId = data.session_id;
	setStatus('Session ready');
	await loadNext();
}

function setMode(newMode){
	mode = newMode;
	nextBtn.textContent = newMode === 'submit' ? 'Submit' : 'Next';
}

function renderQuestion(q){
	currentQuestion = q;
	selectedOptionId = null;
	questionEl.textContent = q.text;
	optionsEl.innerHTML = '';
	q.options.forEach(opt => {
		const btn = document.createElement('button');
		btn.type = 'button';
		btn.className = 'option';
		btn.textContent = opt.text;
		btn.onclick = async () => {
			if (mode !== 'submit') return;
			selectedOptionId = opt.id;
			[...optionsEl.children].forEach(c => c.classList.remove('selected'));
			btn.classList.add('selected');
			nextBtn.disabled = false;
			await handleSubmit();
		};
		optionsEl.appendChild(btn);
	});
	nextBtn.disabled = true;
	setMode('submit');
}

async function loadNext(){
	const url = new URL(API('/api/quiz/next'));
	url.searchParams.set('session_id', sessionId);
	const res = await fetch(url);
	if(!res.ok){ setStatus('Failed to fetch question'); return; }
	const data = await res.json();
	if (data.show_difficulty_change === 'too_easy_increasing_difficulty') {
		showOverlay('Difficulty increasing', 'info');
	} else if (data.show_difficulty_change === 'too_hard_decreasing_difficulty') {
		showOverlay('Difficulty decreasing', 'info');
	}
	renderQuestion(data.question);
	showCard();
}

function disableOptions(){
	[...optionsEl.children].forEach(c => c.setAttribute('disabled','disabled'));
}

async function handleSubmit(){
	if(!selectedOptionId || !currentQuestion) return;
	const res = await fetch(API('/api/quiz/submit'), { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ session_id: sessionId, question_id: currentQuestion.id, selected_option_id: selectedOptionId }) });
	if(!res.ok){ setStatus('Submit failed'); return; }
	const result = await res.json();
	score.total += 1;
	if (result.correct) score.correct += 1;
	updateScore();
	showOverlay(result.correct ? 'Correct!' : 'Wrong', result.correct ? 'good' : 'bad');
	disableOptions();
	nextBtn.disabled = false;
	setMode('next');
	setTimeout(async ()=>{ if (mode === 'next') { nextBtn.disabled = true; await loadNext(); } }, 800);
}

async function handleNext(){
	nextBtn.disabled = true;
	await loadNext();
}

nextBtn.addEventListener('click', async () => {
	if (mode === 'submit') await handleSubmit(); else await handleNext();
});

updateScore();
startSession().catch(()=> setStatus('Failed to start session'));
