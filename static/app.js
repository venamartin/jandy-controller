// State
let lastStatus = null;
let hardwareConfig = null;
let buttonsRendered = false;

// Pending UI commands that haven't been confirmed by the backend yet
const pendingCommands = new Set();

// Modal State
let currentHeatAction = null;
let modalTemp = 85;

// Elements
const airTempEl = document.getElementById('air-temp');
const waterTempEl = document.getElementById('water-temp');
const controlGrid = document.getElementById('control-grid');
const connectionStatus = document.getElementById('connection-status');
const statusDot = document.querySelector('.dot');
const tempModal = document.getElementById('temp-modal');
const modalTitle = document.getElementById('modal-title');
const modalTempValue = document.getElementById('modal-temp-value');
const monitorBanner = document.getElementById('monitor-banner');

const HARDWARE_MAP = [
    { id: 'pool_mode', label: 'Pool Mode', configKey: null, hasTemp: false },
    { id: 'pool_heat', label: 'Pool Heater', configKey: 'has_pool_heater', hasTemp: true },
    { id: 'spa_mode', label: 'Spa Mode', configKey: 'has_spa', hasTemp: false },
    { id: 'spa_heat', label: 'Spa Heater', configKey: 'has_spa_heater', hasTemp: true },
    { id: 'pool_lights', label: 'Pool Lights', configKey: 'has_pool_lights', hasTemp: false },
    { id: 'spa_lights', label: 'Spa Lights', configKey: 'has_spa_lights', hasTemp: false },
    { id: 'deck_lights', label: 'Deck Lights', configKey: 'has_deck_lights', hasTemp: false },
    { id: 'air_blower', label: 'Air Blower', configKey: 'has_blower', hasTemp: false },
    { id: 'cleaner', label: 'Cleaner', configKey: 'has_cleaner', hasTemp: false },
    { id: 'solar', label: 'Solar Heater', configKey: 'has_solar', hasTemp: false },
];

async function pollStatus() {
    try {
        const response = await fetch('/api/status');
        if (!response.ok) throw new Error('Network response was not ok');
        
        const data = await response.json();
        const status = data.status;
        hardwareConfig = data.config;

        // Render buttons on first load
        if (!buttonsRendered) {
            renderButtons();
            buttonsRendered = true;
        }

        // Update Connection Status
        connectionStatus.textContent = 'Connected';
        statusDot.style.backgroundColor = 'var(--success)';
        statusDot.style.boxShadow = '0 0 10px var(--success)';

        // Update Temps
        airTempEl.textContent = status.air_temp ? `${status.air_temp}°` : '--°';
        waterTempEl.textContent = status.water_temp ? `${status.water_temp}°` : '--°';

        // Update Button States
        updateButtonState('pool_mode', status.pool_mode_on);
        updateButtonState('pool_heat', status.pool_heater_on, status.pool_heater_setpoint, status.pool_heater_ena);
        updateButtonState('spa_mode', status.spa_mode_on);
        updateButtonState('spa_heat', status.spa_heater_on, status.spa_heater_setpoint, status.spa_heater_ena);
        updateButtonState('air_blower', status.blower_on);
        updateButtonState('pool_lights', status.pool_lights_on);
        updateButtonState('spa_lights', status.spa_lights_on);
        updateButtonState('deck_lights', status.deck_lights_on);
        updateButtonState('solar', status.solar_on);
        updateButtonState('cleaner', status.cleaner_on);

        updateButtonDisabledStates(status);

        // Monitor Mode Check
        if (status.monitor_mode) {
            monitorBanner.style.display = 'block';
            document.querySelectorAll('.controls button').forEach(btn => btn.disabled = true);
        } else {
            monitorBanner.style.display = 'none';
            // Enable buttons, then rely on updateButtonDisabledStates to do proper business logic disables
            document.querySelectorAll('.controls button').forEach(btn => btn.disabled = false);
            updateButtonDisabledStates(status);
        }

        lastStatus = status;

    } catch (error) {
        console.error('Error fetching status:', error);
        connectionStatus.textContent = 'Disconnected';
        statusDot.style.backgroundColor = 'var(--danger)';
        statusDot.style.boxShadow = '0 0 10px var(--danger)';
    }

    // Loop
    setTimeout(pollStatus, 1000);
}

function renderButtons() {
    controlGrid.innerHTML = '';

    HARDWARE_MAP.forEach(item => {
        // Skip if hardware config explicitly disables it
        if (item.configKey && hardwareConfig && hardwareConfig[item.configKey] === false) {
            return;
        }

        const btn = document.createElement('button');
        btn.className = 'btn';
        btn.id = `btn-${item.id}`;
        
        // Inner HTML
        let html = `<span>${item.label}</span>`;
        if (item.hasTemp) {
            html += `<span class="temp-badge" id="badge-${item.id}">--°</span>`;
        }
        btn.innerHTML = html;

        btn.onclick = () => handleButtonClick(item.id, item.hasTemp);
        controlGrid.appendChild(btn);
    });
}

function updateButtonState(action, isOn, setpoint = null, isEna = false) {
    const btn = document.getElementById(`btn-${action}`);
    if (!btn) return;

    // If there's a pending command for this action, keep it in "loading" state
    // UNLESS the backend status finally matches what we asked for
    if (pendingCommands.has(action)) {
        // Did it resolve?
        // Note: For heaters, we assume the command resolves when the state flips
        const expectedState = btn.dataset.expectedState === 'true';
        if (isOn === expectedState) {
            pendingCommands.delete(action);
            btn.classList.remove('loading');
        } else {
            return; // Still waiting, don't update visual state yet
        }
    }

    if (isOn) {
        if (isEna) {
            btn.classList.add('ena');
            btn.classList.remove('active');
        } else {
            btn.classList.add('active');
            btn.classList.remove('ena');
        }
    } else {
        btn.classList.remove('active', 'ena');
    }

    // Update setpoint badge if applicable
    if (setpoint !== null) {
        const badge = document.getElementById(`badge-${action}`);
        if (badge) badge.textContent = `Set: ${setpoint}°`;
    }
}

function updateButtonDisabledStates(status) {
    const poolHeatBtn = document.getElementById('btn-pool_heat');
    if (poolHeatBtn) {
        poolHeatBtn.disabled = !status.pool_mode_on;
    }

    const spaHeatBtn = document.getElementById('btn-spa_heat');
    if (spaHeatBtn) {
        spaHeatBtn.disabled = !status.spa_mode_on;
    }

    const blowerBtn = document.getElementById('btn-air_blower');
    if (blowerBtn) {
        blowerBtn.disabled = !status.spa_mode_on;
    }

    const cleanerBtn = document.getElementById('btn-cleaner');
    if (cleanerBtn) {
        cleanerBtn.disabled = !status.pool_mode_on;
    }

    const solarBtn = document.getElementById('btn-solar');
    if (solarBtn) {
        solarBtn.disabled = status.spa_mode_on;
    }
}

function handleButtonClick(action, hasTemp) {
    const btn = document.getElementById(`btn-${action}`);
    if (!btn || pendingCommands.has(action)) return;

    // Remove sticky hover/focus states instantly on mobile
    btn.blur();

    const currentlyOn = btn.classList.contains('active') || btn.classList.contains('ena');
    const newState = !currentlyOn;

    // If turning ON a heater, open the temp modal
    if (hasTemp && newState === true) {
        openModal(action);
    } else {
        // Otherwise, send command immediately
        sendCommand(action, newState);
    }
}

async function sendCommand(action, state, temp = null) {
    if (action !== 'all_off') {
        const btn = document.getElementById(`btn-${action}`);
        if (btn) {
            btn.classList.add('loading');
            btn.dataset.expectedState = state.toString();
            pendingCommands.add(action);
        }
    }

    try {
        const payload = { action, state };
        if (temp !== null) payload.temp = temp;

        await fetch('/api/command', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
    } catch (e) {
        console.error("Failed to send command:", e);
        if (action !== 'all_off') {
            pendingCommands.delete(action);
            const btn = document.getElementById(`btn-${action}`);
            if (btn) btn.classList.remove('loading');
        }
    }
}

// Modal Logic
function openModal(action) {
    currentHeatAction = action;
    const label = HARDWARE_MAP.find(i => i.id === action).label;
    modalTitle.textContent = `Set ${label} Temp`;
    
    // Read current setpoint from last status if available
    let currentSetpoint = 85;
    if (lastStatus) {
        if (action === 'pool_heat' && lastStatus.pool_heater_setpoint) currentSetpoint = lastStatus.pool_heater_setpoint;
        if (action === 'spa_heat' && lastStatus.spa_heater_setpoint) currentSetpoint = lastStatus.spa_heater_setpoint;
    }
    
    modalTemp = currentSetpoint;
    updateModalDisplay();
    tempModal.classList.add('show');
}

function closeModal() {
    tempModal.classList.remove('show');
    currentHeatAction = null;
}

function adjustTemp(delta) {
    modalTemp += delta;
    if (modalTemp < 40) modalTemp = 40;
    if (modalTemp > 104) modalTemp = 104;
    updateModalDisplay();
}

function updateModalDisplay() {
    modalTempValue.textContent = modalTemp;
}

function submitTemp() {
    if (currentHeatAction) {
        sendCommand(currentHeatAction, true, modalTemp);
        closeModal();
    }
}

function toggleFullScreen() {
    if (!document.fullscreenElement) {
        document.documentElement.requestFullscreen().catch(err => {
            console.log(`Error attempting to enable fullscreen: ${err.message}`);
        });
    } else {
        if (document.exitFullscreen) {
            document.exitFullscreen();
        }
    }
}

// Start polling
pollStatus();
