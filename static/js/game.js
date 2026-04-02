/* AI Dungeon Master - Game Client */

const API = '/api';
let state = {
    selectedRace: null,
    selectedClass: null,
    abilityScores: [],
    assignedScores: {},
    selectedSkills: [],
    maxSkills: 2,
    selectedCharId: null,
    sessionId: null,
    raceData: [],
    classData: [],
    inCombat: false,
    pendingEncounter: null,
    actionInProgress: false,
};

// =========================================================================
// Utilities
// =========================================================================

async function api(path, options = {}) {
    const resp = await fetch(`${API}${path}`, {
        headers: { 'Content-Type': 'application/json' },
        ...options,
    });
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `API error ${resp.status}`);
    }
    return resp.json();
}

function showScreen(id) {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    document.getElementById(id).classList.add('active');
}

function abilityMod(score) { return Math.floor((score - 10) / 2); }
function modStr(score) { const m = abilityMod(score); return m >= 0 ? `+${m}` : `${m}`; }

function setLoading(loading) {
    state.actionInProgress = loading;
    const btn = document.getElementById('btn-submit');
    const input = document.getElementById('action-text');
    if (btn) { btn.disabled = loading; btn.textContent = loading ? 'Thinking...' : 'Do It'; }
    if (input) input.disabled = loading;
    document.querySelectorAll('.btn-action').forEach(b => b.disabled = loading);
}

// =========================================================================
// Landing Screen
// =========================================================================

async function loadLanding() {
    try {
        const chars = await api('/characters');
        const list = document.getElementById('character-list');
        if (chars.length === 0) {
            list.innerHTML = '<p style="color:var(--text-secondary)">No characters yet. Create one to begin!</p>';
        } else {
            list.innerHTML = chars.map(c => `
                <div class="char-card" onclick="selectCharacter(${c.id}, this)" data-id="${c.id}">
                    <div class="char-card-info">
                        <div class="char-card-name">${c.name}</div>
                        <div class="char-card-detail">${c.race} ${c.class} · Level ${c.level} · HP ${c.hp}</div>
                    </div>
                </div>
            `).join('');
        }

        const advs = await api('/adventures');
        const advList = document.getElementById('adventure-list');
        if (advs.length > 0) {
            advList.innerHTML = advs.map(a => `
                <div class="char-card" onclick="startAdventure('${a.id}')">
                    <div class="char-card-info">
                        <div class="char-card-name">${a.name}</div>
                        <div class="char-card-detail">${a.description.substring(0, 100)}... · Level ${a.level_range[0]}-${a.level_range[1]}</div>
                    </div>
                </div>
            `).join('');
        }
    } catch (e) { console.error('Failed to load landing:', e); }
}

function selectCharacter(id, el) {
    state.selectedCharId = id;
    document.querySelectorAll('#character-list .char-card').forEach(c => c.classList.remove('selected'));
    el.classList.add('selected');
    document.getElementById('adventure-panel').style.display = 'block';
}

async function startAdventure(adventureId) {
    if (!state.selectedCharId) { alert('Select a character first!'); return; }
    setLoading(true);
    try {
        const result = await api('/sessions', {
            method: 'POST',
            body: JSON.stringify({ character_id: state.selectedCharId, adventure_id: adventureId }),
        });
        state.sessionId = result.session_id;
        showScreen('screen-play');
        initGameplay(result);
    } catch (e) { alert('Error starting adventure: ' + e.message); }
    finally { setLoading(false); }
}

// =========================================================================
// Character Creation
// =========================================================================

async function loadCreation() {
    try {
        state.raceData = await api('/races');
        state.classData = await api('/classes');

        document.getElementById('race-options').innerHTML = state.raceData.map(r => {
            const bonuses = Object.entries(r.ability_bonuses).map(([k,v]) => `${k}+${v}`).join(', ');
            return `<div class="option-card" onclick="selectRace('${r.index}', this)">
                <div class="card-name">${r.name}</div>
                <div class="card-detail">${bonuses || 'No bonuses'}</div>
                <div class="card-detail">Speed ${r.speed} · ${r.size}</div>
            </div>`;
        }).join('');

        document.getElementById('class-options').innerHTML = state.classData.map(c =>
            `<div class="option-card" onclick="selectClass('${c.index}', this)">
                <div class="card-name">${c.name}</div>
                <div class="card-detail">Hit Die: d${c.hit_die}</div>
                <div class="card-detail">Saves: ${c.saving_throws.join(', ')}</div>
            </div>`
        ).join('');
    } catch (e) { console.error('Failed to load creation data:', e); }
}

function selectRace(index, el) {
    state.selectedRace = index;
    el.parentElement.querySelectorAll('.option-card').forEach(c => c.classList.remove('selected'));
    el.classList.add('selected');
}
function selectClass(index, el) {
    state.selectedClass = index;
    el.parentElement.querySelectorAll('.option-card').forEach(c => c.classList.remove('selected'));
    el.classList.add('selected');
}
function creationStep2() {
    if (!state.selectedRace || !document.getElementById('char-name').value.trim()) { alert('Enter a name and select a race.'); return; }
    document.getElementById('step-1').style.display = 'none';
    document.getElementById('step-2').style.display = 'block';
}
function creationStep3() {
    if (!state.selectedClass) { alert('Select a class.'); return; }
    document.getElementById('step-2').style.display = 'none';
    document.getElementById('step-3').style.display = 'block';
}
async function rollScores() {
    const result = await api('/ability-scores/roll');
    state.abilityScores = result.scores.sort((a, b) => b - a);
    renderAbilityAssignment();
}
async function useStandardArray() {
    const result = await api('/ability-scores/standard');
    state.abilityScores = result.scores;
    renderAbilityAssignment();
}
function renderAbilityAssignment() {
    const abilities = ['str', 'dex', 'con', 'int', 'wis', 'cha'];
    const labels = { str: 'Strength', dex: 'Dexterity', con: 'Constitution', int: 'Intelligence', wis: 'Wisdom', cha: 'Charisma' };
    const race = state.raceData.find(r => r.index === state.selectedRace);
    const bonuses = race ? race.ability_bonuses : {};
    document.getElementById('ability-assignment').innerHTML = abilities.map(ab => {
        const bonus = bonuses[ab.toUpperCase()] || 0;
        const options = state.abilityScores.map(s => `<option value="${s}">${s}</option>`).join('');
        return `<div class="ability-slot">
            <div class="ability-name">${labels[ab]}</div>
            <select onchange="assignScore('${ab}', this.value)"><option value="">--</option>${options}</select>
            ${bonus ? `<div class="racial-bonus">+${bonus} racial</div>` : ''}
        </div>`;
    }).join('');
}
function assignScore(ability, value) { state.assignedScores[ability] = parseInt(value) || 0; }

async function creationStep4() {
    const assigned = Object.values(state.assignedScores).filter(v => v > 0);
    if (assigned.length < 6) { alert('Assign all 6 ability scores.'); return; }
    const skills = await api(`/classes/${state.selectedClass}/skills`);
    state.maxSkills = skills.choose;
    state.selectedSkills = [];
    document.getElementById('skill-options').innerHTML =
        `<p style="color:var(--text-secondary);grid-column:1/-1">Choose ${skills.choose} skills:</p>` +
        skills.options.map(s => `<label class="skill-option">
            <input type="checkbox" value="${s.index}" onchange="toggleSkill('${s.index}', this)"> ${s.name}
        </label>`).join('');
    document.getElementById('step-3').style.display = 'none';
    document.getElementById('step-4').style.display = 'block';
}
function toggleSkill(skill, cb) {
    if (cb.checked) { if (state.selectedSkills.length >= state.maxSkills) { cb.checked = false; return; } state.selectedSkills.push(skill); }
    else { state.selectedSkills = state.selectedSkills.filter(s => s !== skill); }
}
async function finalizeCharacter() {
    const name = document.getElementById('char-name').value.trim();
    if (!name) { alert('Enter a name!'); return; }
    if (state.selectedSkills.length < state.maxSkills) { alert(`Select ${state.maxSkills} skills.`); return; }
    try {
        const result = await api('/characters', {
            method: 'POST',
            body: JSON.stringify({ name, race: state.selectedRace, char_class: state.selectedClass, ability_scores: state.assignedScores, skill_choices: state.selectedSkills }),
        });
        alert(`${result.name} created! HP: ${result.hp}, AC: ${result.ac}`);
        state.selectedRace = null; state.selectedClass = null; state.abilityScores = []; state.assignedScores = {}; state.selectedSkills = [];
        document.getElementById('char-name').value = '';
        ['step-2','step-3','step-4'].forEach(s => document.getElementById(s).style.display = 'none');
        document.getElementById('step-1').style.display = 'block';
        document.querySelectorAll('.option-card').forEach(c => c.classList.remove('selected'));
        showScreen('screen-landing');
        loadLanding();
    } catch (e) { alert('Error: ' + e.message); }
}

// =========================================================================
// Gameplay — Display
// =========================================================================

function initGameplay(sessionData) {
    document.getElementById('narrative-log').innerHTML = '';
    document.getElementById('combat-panel').style.display = 'none';
    state.inCombat = false;
    appendNarrative(sessionData.narrative, 'ai');
    if (sessionData.character) updateCharSheet(sessionData.character);
    if (sessionData.scene) { updateScene(sessionData.scene); checkForEncounters(sessionData.scene); }
}

function appendNarrative(text, type = 'ai') {
    const log = document.getElementById('narrative-log');
    const entry = document.createElement('div');
    entry.className = `log-entry ${type}`;
    if (type === 'ai') {
        entry.innerHTML = text.split(/\n\n+/).map(p => `<p>${p.replace(/\n/g, '<br>')}</p>`).join('');
    } else { entry.textContent = text; }
    log.appendChild(entry);
    log.scrollTop = log.scrollHeight;
}

function appendRoll(rollData) {
    const log = document.getElementById('narrative-log');
    const entry = document.createElement('div');
    entry.className = 'log-entry roll';
    if (rollData.type === 'attack') {
        const hm = rollData.hit ? 'HIT' : 'MISS';
        entry.textContent = `⚔ Attack: ${rollData.roll} vs AC ${rollData.target_ac} → ${hm}`;
        if (rollData.hit) entry.textContent += ` | ${rollData.damage} ${rollData.damage_type} damage`;
        if (rollData.critical) entry.textContent += ' ★ CRITICAL!';
    } else if (rollData.type === 'monster_attack') {
        const hm = rollData.hit ? 'HIT' : 'MISS';
        entry.textContent = `🗡 ${rollData.attacker} (${rollData.action}): ${rollData.roll||'?'} vs AC ${rollData.target_ac||'?'} → ${hm}`;
        if (rollData.hit) entry.textContent += ` | ${rollData.damage} ${rollData.damage_type||''} damage to you!`;
        if (rollData.critical) entry.textContent += ' ★ CRITICAL!';
        entry.style.color = 'var(--danger)';
    } else if (rollData.type === 'skill_check') {
        entry.textContent = `🎲 ${rollData.skill}: ${rollData.roll}`;
        if (rollData.dc) entry.textContent += ` vs DC ${rollData.dc} → ${rollData.success ? 'SUCCESS' : 'FAILURE'}`;
    }
    log.appendChild(entry);
    log.scrollTop = log.scrollHeight;
}

function appendSystem(text) {
    const log = document.getElementById('narrative-log');
    const entry = document.createElement('div');
    entry.className = 'log-entry system';
    entry.textContent = `⚙ ${text}`;
    log.appendChild(entry);
    log.scrollTop = log.scrollHeight;
}

function updateCharSheet(char) {
    document.getElementById('cs-name').textContent = char.name;
    document.getElementById('cs-race-class').textContent = `${char.race} ${char.class}`;
    document.getElementById('cs-level').textContent = `Level ${char.level}`;
    document.getElementById('cs-hp').textContent = char.hp;
    document.getElementById('cs-ac').textContent = char.ac;
    const parts = char.hp.split('/');
    const pct = (parseInt(parts[0]) / parseInt(parts[1])) * 100;
    const bar = document.getElementById('cs-hp-bar');
    bar.style.width = `${pct}%`;
    bar.style.backgroundColor = pct > 50 ? 'var(--hp-green)' : pct > 25 ? 'var(--hp-yellow)' : 'var(--hp-red)';
    document.getElementById('cs-abilities').innerHTML = Object.entries(char.abilities || {}).map(([name, score]) =>
        `<div class="cs-ability"><div class="cs-ability-name">${name}</div><div class="cs-ability-score">${score}</div><div class="cs-ability-mod">${modStr(score)}</div></div>`
    ).join('');
}

function updateScene(scene) {
    document.getElementById('scene-name').textContent = scene.name || 'Unknown';
    document.getElementById('scene-exits').innerHTML = (scene.exits || []).map(e =>
        `<div class="scene-exit" onclick="doAction('move', {direction:'${e.direction}'})">
            <span class="exit-dir">${e.direction}</span>: ${e.description.substring(0, 80)}${e.locked ? ' 🔒' : ''}
        </div>`
    ).join('');
    document.getElementById('scene-npcs').innerHTML = (scene.npcs || []).map(n =>
        `<div class="scene-npc" onclick="talkToNPC('${n.name.replace(/'/g, "\\'")}')">
            💬 <strong>${n.name}</strong> <span style="color:var(--text-secondary)">(${n.disposition})</span>
        </div>`
    ).join('');
    updateActionButtons(scene);
}

function checkForEncounters(scene) {
    const encounters = scene.pending_encounters || [];
    if (encounters.length > 0) {
        const enc = encounters[0];
        state.pendingEncounter = enc;
        appendSystem(`Encounter available: ${enc.description}`);
        document.getElementById('action-buttons').innerHTML +=
            `<button onclick="triggerEncounter('${enc.id}')" class="btn btn-action" style="background:var(--danger);border-color:var(--danger)">⚔ Engage!</button>`;
    }
}

function updateActionButtons(scene) {
    let html = '';
    if (state.inCombat) {
        html += `<button onclick="doAction('look', {})" class="btn btn-action">👁 Look</button>`;
    } else {
        html += `<button onclick="doAction('look', {})" class="btn btn-action">👁 Look Around</button>`;
        html += `<button onclick="doAction('search', {skill:'perception'})" class="btn btn-action">🔍 Search</button>`;
        if (scene && scene.rest_allowed) {
            html += `<button onclick="doAction('rest', {type:'short'})" class="btn btn-action">⛺ Short Rest</button>`;
            html += `<button onclick="doAction('rest', {type:'long'})" class="btn btn-action">🏕 Long Rest</button>`;
        }
    }
    document.getElementById('action-buttons').innerHTML = html;
}

function updateCombat(enemies) {
    const panel = document.getElementById('combat-panel');
    if (!enemies || enemies.length === 0) { panel.style.display = 'none'; state.inCombat = false; return; }
    panel.style.display = 'block';
    state.inCombat = true;
    document.getElementById('combat-enemies').innerHTML = enemies.map(e => {
        const dead = !e.alive;
        const nameEsc = e.name.replace(/'/g, "\\'");
        return `<div class="combat-enemy ${dead ? 'enemy-dead' : ''}" ${!dead ? `onclick="doAction('attack', {target:'${nameEsc}'})" style="cursor:pointer"` : ''}>
            <span class="enemy-name">${dead ? '💀' : '⚔'} ${e.name}</span>
            <span>${e.hp} HP · AC ${e.ac}</span>
        </div>`;
    }).join('');
}

function talkToNPC(npcName) {
    const topic = prompt(`What do you want to say to ${npcName}?`, 'hello');
    if (topic !== null) doAction('talk', { npc: npcName, topic });
}

// =========================================================================
// Combat Flow
// =========================================================================

async function triggerEncounter(encounterId) {
    if (state.actionInProgress) return;
    setLoading(true);
    try {
        const result = await api(`/sessions/${state.sessionId}/combat/start`, {
            method: 'POST',
            body: JSON.stringify({ encounter_id: encounterId }),
        });
        state.inCombat = true;
        state.pendingEncounter = null;
        if (result.combat && result.combat.initiative_order) {
            appendSystem('Initiative: ' + result.combat.initiative_order.map(c => `${c.name} (${c.initiative})`).join(' → '));
        }
        if (result.combat && result.combat.monsters_spawned) {
            updateCombat(result.combat.monsters_spawned.map(m => ({ name: m.name, hp: `${m.hp}/${m.hp}`, ac: m.ac, alive: true })));
        }
        if (result.narrative) appendNarrative(result.narrative, 'ai');
        updateActionButtons({});
    } catch (e) { appendSystem(`Error starting combat: ${e.message}`); }
    finally { setLoading(false); }
}

// =========================================================================
// Main Action Handler
// =========================================================================

async function doAction(actionType, params) {
    if (!state.sessionId || state.actionInProgress) return;
    setLoading(true);

    const msgs = {
        move: `> You head ${params.direction || 'onward'}.`,
        talk: `> You speak with ${params.npc || 'someone'}${params.topic && params.topic !== 'hello' ? ': "' + params.topic + '"' : ''}.`,
        attack: `> You attack ${params.target}!`,
        search: `> You search the area carefully.`,
        look: `> You observe your surroundings.`,
        rest: `> You take a ${params.type || 'short'} rest.`,
        free_action: `> ${params.text || '...'}`,
    };
    if (msgs[actionType]) appendNarrative(msgs[actionType], 'player');

    try {
        const result = await api(`/sessions/${state.sessionId}/action`, {
            method: 'POST',
            body: JSON.stringify({ action_type: actionType, params }),
        });

        const ar = result.action_result || {};

        // Show rolls
        if (ar.rolls) ar.rolls.forEach(r => appendRoll(r));

        // Show narrative
        if (result.narrative) appendNarrative(result.narrative, 'ai');

        // Show errors
        if (ar.error) appendSystem(ar.error);

        // Update UI
        if (result.character) updateCharSheet(result.character);
        if (result.scene) {
            updateScene(result.scene);
            if (ar.scene_changed) checkForEncounters(result.scene);
        }

        // Combat state
        if (ar.combat_started) { appendSystem('Combat has begun!'); state.inCombat = true; }
        if (ar.combat_ended) {
            appendSystem('Combat is over!');
            state.inCombat = false;
            document.getElementById('combat-panel').style.display = 'none';
            if (result.scene) updateActionButtons(result.scene);
        }

        // Update combat panel if we're in combat and got enemy data
        if (result.in_combat) {
            // Refresh combat entity state
            try {
                const ss = await api(`/sessions/${state.sessionId}/combat/entities`);
                if (ss && ss.length > 0) updateCombat(ss);
            } catch (_) { /* endpoint may not exist yet */ }
        }

        // Items found
        if (ar.items_found) ar.items_found.forEach(item => appendSystem(`Found: ${item.name} — ${item.description}`));

    } catch (e) { appendSystem(`Error: ${e.message}`); }
    finally { setLoading(false); }
}

async function submitFreeAction() {
    const input = document.getElementById('action-text');
    const text = input.value.trim();
    if (!text || state.actionInProgress) return;
    const lower = text.toLowerCase();

    if (/^(go|move|head|walk)\s/i.test(lower)) { await doAction('move', { direction: text.replace(/^(go|move|head|walk)\s+/i, '') }); }
    else if (/^(talk|speak|ask)\s/i.test(lower)) {
        const rest = text.replace(/^(talk|speak|ask)\s+/i, '');
        const m = rest.match(/(?:to\s+)?(.+?)\s+about\s+(.+)/i);
        await doAction('talk', m ? { npc: m[1], topic: m[2] } : { npc: rest.replace(/^to\s+/i, ''), topic: '' });
    }
    else if (/^(attack|fight|hit|strike)\s/i.test(lower)) { await doAction('attack', { target: text.replace(/^(attack|fight|hit|strike)\s+/i, '') }); }
    else if (/^(search|investigate|examine)/i.test(lower)) { await doAction('search', { skill: 'perception' }); }
    else if (/^(look|observe)/i.test(lower)) { await doAction('look', { target: text.replace(/^(look|observe)\s*/i, '') }); }
    else if (/^(short rest|rest)$/i.test(lower)) { await doAction('rest', { type: 'short' }); }
    else if (/^(long rest|sleep|camp)$/i.test(lower)) { await doAction('rest', { type: 'long' }); }
    else { await doAction('free_action', { text }); }

    input.value = '';
}

document.addEventListener('DOMContentLoaded', () => {
    const input = document.getElementById('action-text');
    if (input) input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submitFreeAction(); } });
});

// =========================================================================
// Init
// =========================================================================
loadLanding();
loadCreation();
