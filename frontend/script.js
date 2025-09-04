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

let countdownInterval = null;

function setStatus(text, showTimer = false, duration = 0){ 
	statusEl.textContent = text; 
	statusEl.className = showTimer ? 'status-with-timer' : 'status-normal';
	
	// Clear any existing countdown
	if (countdownInterval) {
		clearInterval(countdownInterval);
		countdownInterval = null;
	}
	
	// Start countdown timer if requested
	if (showTimer && duration > 0) {
		let remaining = Math.ceil(duration / 1000);
		statusEl.innerHTML = `${text} <span class="countdown">(${remaining}s)</span>`;
		
		countdownInterval = setInterval(() => {
			remaining--;
			if (remaining <= 0) {
				clearInterval(countdownInterval);
				countdownInterval = null;
				statusEl.innerHTML = text;
			} else {
				statusEl.innerHTML = `${text} <span class="countdown">(${remaining}s)</span>`;
			}
		}, 1000);
	}
}
function showCard(){ 
	cardEl.classList.remove('hidden');
}
function hideCard(){ 
	cardEl.classList.add('hidden');
}
function playSound(type) {
	try {
		const audioContext = new (window.AudioContext || window.webkitAudioContext)();
		const oscillator = audioContext.createOscillator();
		const gainNode = audioContext.createGain();
		
		oscillator.connect(gainNode);
		gainNode.connect(audioContext.destination);
		
		if (type === 'increase') {
			// Longer, more satisfying rising tone for difficulty increase
			oscillator.frequency.setValueAtTime(600, audioContext.currentTime);
			oscillator.frequency.exponentialRampToValueAtTime(1000, audioContext.currentTime + 0.4);
			oscillator.frequency.exponentialRampToValueAtTime(1400, audioContext.currentTime + 0.8);
		} else if (type === 'decrease') {
			// Longer, more satisfying falling tone for difficulty decrease
			oscillator.frequency.setValueAtTime(500, audioContext.currentTime);
			oscillator.frequency.exponentialRampToValueAtTime(300, audioContext.currentTime + 0.4);
			oscillator.frequency.exponentialRampToValueAtTime(150, audioContext.currentTime + 0.8);
		} else if (type === 'correct') {
			// Longer, more satisfying chord progression for correct answer
			oscillator.frequency.setValueAtTime(523, audioContext.currentTime); // C5
			oscillator.frequency.setValueAtTime(659, audioContext.currentTime + 0.15); // E5
			oscillator.frequency.setValueAtTime(784, audioContext.currentTime + 0.3); // G5
			oscillator.frequency.setValueAtTime(1047, audioContext.currentTime + 0.45); // C6
		} else if (type === 'wrong') {
			// Harsh, attention-grabbing sound for wrong answer
			oscillator.frequency.setValueAtTime(300, audioContext.currentTime);
			oscillator.frequency.setValueAtTime(250, audioContext.currentTime + 0.1);
			oscillator.frequency.setValueAtTime(300, audioContext.currentTime + 0.2);
			oscillator.frequency.setValueAtTime(200, audioContext.currentTime + 0.3);
			oscillator.frequency.setValueAtTime(150, audioContext.currentTime + 0.4);
		}
		
		// Longer duration and more gradual fade with louder volume
		const duration = type === 'correct' ? 0.8 : 0.6;
		const baseVolume = type === 'wrong' ? 0.4 : 0.18; // Much louder for wrong answers
		gainNode.gain.setValueAtTime(baseVolume, audioContext.currentTime);
		gainNode.gain.exponentialRampToValueAtTime(baseVolume * 0.7, audioContext.currentTime + duration * 0.3);
		gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + duration);
		
		oscillator.start(audioContext.currentTime);
		oscillator.stop(audioContext.currentTime + duration);
	} catch (e) {
		// Silently fail if audio context is not supported
	}
}

function showOverlay(message, variant='info'){ 
	overlayContent.textContent = message; 
	overlayContent.className = `overlay-content ${variant}`; 
	overlay.classList.remove('hidden'); 
	
	// Play sound based on variant
	if (variant === 'good') playSound('correct');
	else if (variant === 'bad') playSound('wrong');
	
	setTimeout(()=>overlay.classList.add('hidden'), 2000); 
}
function updateScore(){ scoreEl.textContent = `Score: ${score.correct} / ${score.total}`; }

async function startSession(){
	const hpLoadingMessages = [
		'Preparing your wand...',
		'Sorting you into a house...',
		'Loading magical questions...',
		'Consulting the Sorting Hat...',
		'Gathering potion ingredients...',
		'Opening the Chamber of Secrets...',
		'Summoning questions from the library...',
		'Preparing for your O.W.L.s...',
		'Loading questions from Hogwarts...',
		'Consulting Professor McGonagall...'
	];
	
	let messageIndex = 0;
	const loadingInterval = setInterval(() => {
		setStatus(hpLoadingMessages[messageIndex], true, 800); // Show timer for each message
		messageIndex = (messageIndex + 1) % hpLoadingMessages.length;
	}, 800);
	
	const res = await fetch(API('/api/session/start'), { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({}) });
	const data = await res.json();
	sessionId = data.session_id;
	
	clearInterval(loadingInterval);
	setStatus(''); // Remove status message completely
	await loadNext();
}

function setMode(newMode){
	mode = newMode;
	if (newMode === 'submit') {
		nextBtn.textContent = 'Submit';
		nextBtn.className = 'submit-btn';
		nextBtn.disabled = true; // Disabled until option is selected
	} else {
		// Hide button during auto-advance period
		nextBtn.style.display = 'none';
	}
}

function renderQuestion(q){
	currentQuestion = q;
	selectedOptionId = null;
	questionEl.textContent = q.text;
	optionsEl.innerHTML = '';
	q.options.forEach((opt, index) => {
		const btn = document.createElement('button');
		btn.type = 'button';
		btn.className = 'option';
		btn.innerHTML = `<span class="option-text">${opt.text}</span><span class="option-label">${index + 1}</span>`;
		btn.dataset.optionIndex = index;
		btn.dataset.optionId = opt.id;
		btn.onclick = async () => {
			if (mode !== 'submit') return;
			selectedOptionId = opt.id;
			[...optionsEl.children].forEach(c => c.classList.remove('selected'));
			btn.classList.add('selected');
			nextBtn.disabled = false;
			// Don't auto-submit immediately - let user click submit or use keyboard
		};
		optionsEl.appendChild(btn);
	});
	nextBtn.style.display = 'block'; // Show button for new question
	nextBtn.disabled = true;
	setMode('submit');
}

async function loadNext(){
	console.log('=== LOAD NEXT DEBUG ===');
	console.log('Loading question number:', score.total + 1);
	console.log('Session ID:', sessionId);
	console.log('Timestamp:', new Date().toISOString());
	
	// Don't hide card during loading - just let it stay visible
	
	// Show HP-themed loading message while fetching
	const hpLoadingMessages = [
		'Consulting the library of magical knowledge...',
		'Brewing your next question...',
		'Summoning a new challenge...',
		'Preparing your next magical test...',
		'Gathering wisdom from the wizarding world...'
	];
	const randomLoadingMessage = hpLoadingMessages[Math.floor(Math.random() * hpLoadingMessages.length)];
	setStatus(randomLoadingMessage, true, 3000); // Show timer for 3 seconds
	
	const url = new URL(API('/api/quiz/next'));
	url.searchParams.set('session_id', sessionId);
	let res = await fetch(url);
	if(!res.ok){
		console.log('First fetch failed, retrying...');
		const hpRetryMessages = [
			'Casting a more powerful spell...',
			'Consulting the Room of Requirement...',
			'Asking the portraits for help...',
			'Summoning additional magical knowledge...',
			'Brewing a stronger potion...'
		];
		const randomRetryMessage = hpRetryMessages[Math.floor(Math.random() * hpRetryMessages.length)];
		setStatus(randomRetryMessage, true, 2000); // Show timer for 2 seconds
		// Retry with longer delay for window completion scenarios
		await new Promise(r=>setTimeout(r, 800));
		res = await fetch(url);
		if(!res.ok){ 
			console.log('Second fetch failed, final retry...');
			const hpFinalMessages = [
				'Almost ready... The magic is working...',
				'Final incantation in progress...',
				'Preparing your magical challenge...',
				'The spell is nearly complete...',
				'Gathering the last magical ingredients...'
			];
			const randomFinalMessage = hpFinalMessages[Math.floor(Math.random() * hpFinalMessages.length)];
			setStatus(randomFinalMessage, true, 1500); // Show timer for 1.5 seconds
			// Final retry with even longer delay
			await new Promise(r=>setTimeout(r, 1200));
			res = await fetch(url);
			if(!res.ok){ 
				console.error('All retries failed');
				setStatus('The magic failed! Please try again.'); 
				return; 
			}
		}
	}
	const data = await res.json();
	console.log('Question loaded:', data.question?.id);
	console.log('Show difficulty change:', data.show_difficulty_change);
	console.log('Question difficulty:', data.question?.difficulty);
	console.log('======================');
	if (data.show_difficulty_change === 'too_easy_increasing_difficulty') {
		showOverlay('Difficulty increasing', 'info');
		playSound('increase');
	} else if (data.show_difficulty_change === 'too_hard_decreasing_difficulty') {
		showOverlay('Difficulty decreasing', 'info');
		playSound('decrease');
	}
	renderQuestion(data.question);
	showCard();
	setStatus(''); // Clear loading message
}

function disableOptions(){
	[...optionsEl.children].forEach(c => c.setAttribute('disabled','disabled'));
}

function highlightAnswers(isCorrect, correctAnswerText){
	// Remove any existing highlights
	[...optionsEl.children].forEach(btn => {
		btn.classList.remove('correct', 'wrong', 'selected');
	});
	
	if (isCorrect) {
		// Find and highlight the selected (correct) option
		const selectedBtn = [...optionsEl.children].find(btn => btn.dataset.optionId === selectedOptionId);
		if (selectedBtn) {
			selectedBtn.classList.add('correct');
		}
	} else {
		// Find and highlight the wrong selected option
		const selectedBtn = [...optionsEl.children].find(btn => btn.dataset.optionId === selectedOptionId);
		if (selectedBtn) {
			selectedBtn.classList.add('wrong');
		}
		
		// Find and highlight the correct option
		if (correctAnswerText) {
			const correctBtn = [...optionsEl.children].find(btn => {
				const optionText = btn.querySelector('.option-text').textContent;
				return optionText === correctAnswerText;
			});
			if (correctBtn) {
				correctBtn.classList.add('correct');
			}
		}
	}
}

async function handleSubmit(){
	if(!selectedOptionId || !currentQuestion) return;
	
	// Frontend logging for debugging
	console.log('=== SUBMIT DEBUG ===');
	console.log('Question number:', score.total + 1);
	console.log('Question ID:', currentQuestion.id);
	console.log('Selected option ID:', selectedOptionId);
	console.log('Session ID:', sessionId);
	console.log('Timestamp:', new Date().toISOString());
	
	const res = await fetch(API('/api/quiz/submit'), { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ session_id: sessionId, question_id: currentQuestion.id, selected_option_id: selectedOptionId }) });
	if(!res.ok){ 
		console.error('Submit failed:', res.status, res.statusText);
		setStatus('Submit failed'); 
		return; 
	}
	const result = await res.json();
	
	console.log('Submit response:', result);
	console.log('Window completed:', result.window_completed);
	console.log('==================');
	
	score.total += 1;
	if (result.correct) score.correct += 1;
	updateScore();
	
	// Highlight answers inline
	highlightAnswers(result.correct, result.correct_answer_text);
	
	// Play sound
	playSound(result.correct ? 'correct' : 'wrong');
	
	disableOptions();
	setMode('next'); // This will hide the button
	
	// Show HP-themed loading message if window completed (difficulty adjustment happening)
	if (result.window_completed) {
		const hpMessages = [
			'Professor McGonagall is evaluating your performance...',
			'The Sorting Hat is analyzing your answers...',
			'Dumbledore is adjusting the difficulty...',
			'Preparing your next magical challenge...',
			'The Marauder\'s Map is charting your progress...',
			'Consulting the library for harder questions...',
			'Brewing more challenging potions...',
			'Summoning advanced magical knowledge...'
		];
		const randomMessage = hpMessages[Math.floor(Math.random() * hpMessages.length)];
		setStatus(randomMessage, true, 6000); // Show timer for 6 seconds (more realistic for API delay)
		// Longer delay for window completion to allow background generation
		const delay = 6000;
		setTimeout(async ()=>{ 
			if (mode === 'next') { 
				nextBtn.disabled = true; 
				await loadNext(); 
			} 
		}, delay);
	} else {
		// Standard delay for normal questions
		const delay = 2000;
		setTimeout(async ()=>{ 
			if (mode === 'next') { 
				nextBtn.disabled = true; 
				await loadNext(); 
			} 
		}, delay);
	}
}

nextBtn.addEventListener('click', async () => {
	if (mode === 'submit') await handleSubmit();
});

// Keyboard shortcuts for quick answering
document.addEventListener('keydown', async (e) => {
	if (mode !== 'submit' || !currentQuestion) return;
	
	const key = e.key.toLowerCase();
	const optionIndex = parseInt(key) - 1; // Convert 1,2,3,4 to 0,1,2,3
	
	if (optionIndex >= 0 && optionIndex < 4 && currentQuestion.options[optionIndex]) {
		e.preventDefault();
		// Auto-submit on keyboard selection for fluid UX
		selectedOptionId = currentQuestion.options[optionIndex].id;
		[...optionsEl.children].forEach(c => c.classList.remove('selected'));
		const optionBtn = optionsEl.children[optionIndex];
		optionBtn.classList.add('selected');
		await handleSubmit();
	} else if (key === 'enter' && selectedOptionId) {
		// Enter key to submit when option is selected
		e.preventDefault();
		await handleSubmit();
	}
});

updateScore();
startSession().catch(()=> setStatus('Failed to start session'));
