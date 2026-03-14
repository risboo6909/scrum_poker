const voteOptions = [1, 2, 3, 5, 8, 13, 21];
const pollIntervalMs = 2000;
const basePath = window.APP_BASE_PATH || "";
const roomPathPrefix = `${basePath}/room/`;
const currentPath = window.location.pathname;

function extractRoomId(pathname) {
  if (!pathname.startsWith(roomPathPrefix)) {
    return null;
  }

  const rest = pathname.slice(roomPathPrefix.length);
  const roomId = rest.split("/").filter(Boolean)[0];
  return roomId || null;
}

const state = {
  roomId: extractRoomId(currentPath),
  participantId: null,
  room: null,
  viewer: null,
};
let roomSocket = null;
let currentTheme = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
let lastRenderedPhase = null;
let confettiTimeoutId = null;

const authView = document.querySelector("#auth-view");
const roomView = document.querySelector("#room-view");
const createForm = document.querySelector("#create-form");
const joinForm = document.querySelector("#join-form");
const participantsNode = document.querySelector("#participants");
const votePanel = document.querySelector("#vote-panel");
const voteOptionsNode = document.querySelector("#vote-options");
const statsPanel = document.querySelector("#stats-panel");
const phaseBadge = document.querySelector("#phase-badge");
const roomLink = document.querySelector("#room-link");
const copyRoomLinkButton = document.querySelector("#copy-room-link");
const viewerLabel = document.querySelector("#viewer-label");
const voteStatus = document.querySelector("#vote-status");
const medianValue = document.querySelector("#median-value");
const modeValue = document.querySelector("#mode-value");
const leaderActions = document.querySelector("#leader-actions");
const messageNode = document.querySelector("#message");
const themeToggle = document.querySelector("#theme-toggle");

const startButton = document.querySelector("#start-button");
const revealButton = document.querySelector("#reveal-button");
const panelNode = document.querySelector(".panel");

function applyTheme(theme) {
  currentTheme = theme === "dark" ? "dark" : "light";
  document.documentElement.dataset.theme = currentTheme;
  localStorage.setItem("scrum-poker:theme", currentTheme);
  themeToggle.textContent = currentTheme === "dark" ? "Light theme" : "Dark theme";
}

function roomStorageKey(roomId) {
  return `scrum-poker:${roomId}`;
}

function setMessage(text, isError = false) {
  messageNode.textContent = text;
  messageNode.classList.toggle("hidden", !text);
  messageNode.classList.toggle("error", isError);
}

function clearMessage() {
  setMessage("");
}

async function copyText(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const tempInput = document.createElement("input");
  tempInput.value = text;
  document.body.appendChild(tempInput);
  tempInput.select();
  document.execCommand("copy");
  tempInput.remove();
}

function clearConfetti() {
  const existing = document.querySelector(".confetti-layer");
  if (existing) {
    existing.remove();
  }
  if (confettiTimeoutId) {
    clearTimeout(confettiTimeoutId);
    confettiTimeoutId = null;
  }
}

function launchConfetti() {
  clearConfetti();

  const layer = document.createElement("div");
  layer.className = "confetti-layer";
  const colors = ["#ef7b5d", "#79c59b", "#f4c95d", "#5d8bef", "#f08bd2"];

  for (let index = 0; index < 36; index += 1) {
    const piece = document.createElement("span");
    piece.className = "confetti-piece";
    const fromLeft = index % 2 === 0;
    piece.classList.add(fromLeft ? "from-left" : "from-right");
    piece.style.left = fromLeft ? "34px" : "auto";
    piece.style.right = fromLeft ? "auto" : "34px";
    piece.style.bottom = "20px";
    piece.style.background = colors[index % colors.length];
    const horizontal = fromLeft
      ? 80 + Math.random() * 220
      : -(80 + Math.random() * 220);
    const vertical = -(260 + Math.random() * 300);
    piece.style.setProperty("--confetti-x", `${horizontal}px`);
    piece.style.setProperty("--confetti-y", `${vertical}px`);
    piece.style.setProperty("--confetti-rotate", `${Math.random() * 720 - 360}deg`);
    piece.style.animationDelay = `${Math.random() * 120}ms`;
    piece.style.animationDuration = `${950 + Math.random() * 450}ms`;
    layer.appendChild(piece);
  }

  panelNode.appendChild(layer);
  confettiTimeoutId = window.setTimeout(() => {
    layer.remove();
    confettiTimeoutId = null;
  }, 1900);
}

function updateStateFromPayload(payload) {
  state.room = payload.room;
  state.viewer = payload.viewer;
  render();
}

async function api(path, options = {}) {
  const response = await fetch(`${basePath}${path}`, {
    headers: {
      "Content-Type": "application/json",
    },
    ...options,
  });

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || "Request failed");
  }
  return data;
}

function persistParticipant() {
  if (!state.roomId || !state.participantId) {
    return;
  }
  localStorage.setItem(roomStorageKey(state.roomId), state.participantId);
}

function restoreParticipant() {
  if (!state.roomId) {
    return;
  }
  state.participantId = localStorage.getItem(roomStorageKey(state.roomId));
}

function renderVoteOptions() {
  voteOptionsNode.innerHTML = "";
  const currentVote = state.viewer?.currentVote ?? null;

  voteOptions.forEach((value) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = String(value);
    button.className = "vote-card";
    if (currentVote === value && state.room) {
      button.classList.add("selected");
    }
    button.addEventListener("click", async () => {
      try {
        clearMessage();
        await api(`/api/rooms/${state.roomId}/vote`, {
          method: "POST",
          body: JSON.stringify({
            participantId: state.participantId,
            value,
          }),
        });
      } catch (error) {
        setMessage(error.message, true);
      }
    });
    voteOptionsNode.appendChild(button);
  });
}

function currentParticipant() {
  return state.room?.participants.find((participant) => participant.id === state.participantId);
}

function formatPhase(phase) {
  if (phase === "voting") return "Voting";
  if (phase === "revealed") return "Revealed";
  return "Lobby";
}

function renderParticipants() {
  participantsNode.innerHTML = "";
  const viewer = currentParticipant();
  const shouldAnimateReveal = lastRenderedPhase !== "revealed" && state.room.phase === "revealed";

  state.room.participants.forEach((participant, index) => {
    const item = document.createElement("article");
    item.className = "participant-card";
    item.style.setProperty("--flip-delay", `${index * 70}ms`);

    const title = document.createElement("strong");
    title.textContent = participant.name;

    const meta = document.createElement("span");
    meta.className = "muted";

    const labels = [];
    if (participant.isLeader) labels.push("leader");
    if (viewer?.id === participant.id) labels.push("you");

    if (state.room.phase === "revealed") {
      meta.textContent = participant.vote !== null ? `vote: ${participant.vote}` : "no vote";
    } else {
      meta.textContent = participant.hasVoted ? "voted" : "waiting";
    }

    const labelNode = document.createElement("span");
    labelNode.className = "pill";
    labelNode.textContent = labels.join(" / ") || "participant";

    const flipCard = document.createElement("div");
    flipCard.className = "flip-card";

    const flipInner = document.createElement("div");
    flipInner.className = "flip-card-inner";

    const cardFront = document.createElement("div");
    cardFront.className = "flip-face flip-front";
    cardFront.textContent = "?";

    const cardBack = document.createElement("div");
    cardBack.className = "flip-face flip-back";
    cardBack.textContent = participant.vote !== null ? String(participant.vote) : "-";

    flipInner.appendChild(cardFront);
    flipInner.appendChild(cardBack);
    flipCard.appendChild(flipInner);

    item.appendChild(title);
    item.appendChild(flipCard);
    item.appendChild(labelNode);
    item.appendChild(meta);
    participantsNode.appendChild(item);

    if (state.room.phase === "revealed") {
      if (shouldAnimateReveal) {
        requestAnimationFrame(() => {
          item.classList.add("revealed");
        });
      } else {
        item.classList.add("revealed");
      }
    }
  });
}

function renderStats() {
  const stats = state.room.stats;
  const visible = state.room.phase === "revealed" && stats;
  statsPanel.classList.toggle("hidden", !visible);
  if (!visible) {
    return;
  }

  medianValue.textContent = String(stats.median);
  modeValue.textContent = stats.mode === null ? "-" : String(stats.mode);
}

function renderLeaderControls() {
  const isLeader = !!state.viewer?.isLeader;
  leaderActions.classList.toggle("hidden", !isLeader);
  if (!isLeader) {
    return;
  }

  startButton.disabled = state.room.phase === "voting";
  revealButton.disabled = state.room.phase !== "voting";
}

function renderVotePanel() {
  const viewer = currentParticipant();
  const canVote = state.room.phase === "voting" && !!viewer;
  const viewerVote = state.viewer?.currentVote ?? null;
  votePanel.classList.toggle("hidden", !viewer);

  if (!viewer) {
    return;
  }

  if (state.room.phase === "voting") {
    voteStatus.textContent = viewer.hasVoted ? "Vote saved" : "Pick a card";
  } else if (state.room.phase === "revealed") {
    voteStatus.textContent = viewer.vote !== null ? `You voted ${viewer.vote}` : "You did not vote";
  } else {
    voteStatus.textContent = "Waiting for the leader to start";
  }

  Array.from(voteOptionsNode.children).forEach((button) => {
    button.disabled = !canVote;
    button.classList.remove("selected");
    if (state.room.phase === "voting" && viewerVote !== null && Number(button.textContent) === viewerVote) {
      button.classList.add("selected");
    }
    if (state.room.phase === "revealed" && viewerVote !== null && Number(button.textContent) === viewerVote) {
      button.classList.add("selected");
    }
  });
}

function render() {
  if (!state.room) {
    authView.classList.remove("hidden");
    roomView.classList.add("hidden");
    createForm.classList.toggle("hidden", !!state.roomId);
    joinForm.classList.toggle("hidden", !state.roomId);
    clearConfetti();
    lastRenderedPhase = null;
    return;
  }

  authView.classList.add("hidden");
  roomView.classList.remove("hidden");

  phaseBadge.textContent = formatPhase(state.room.phase);
  roomLink.textContent = `${window.location.origin}${basePath}/room/${state.roomId}`;
  roomLink.href = roomLink.textContent;
  viewerLabel.textContent = state.viewer?.name
    ? `${state.viewer.name}${state.viewer.isLeader ? " (leader)" : ""}`
    : "";

  renderParticipants();
  renderLeaderControls();
  renderVotePanel();
  renderStats();

  if (
    lastRenderedPhase !== "revealed" &&
    state.room.phase === "revealed" &&
    state.room.stats?.unanimous
  ) {
    launchConfetti();
  }

  lastRenderedPhase = state.room.phase;
}

async function refreshRoom() {
  if (!state.roomId || !state.participantId) {
    return;
  }

  const data = await api(
    `/api/rooms/${state.roomId}?participantId=${encodeURIComponent(state.participantId)}`
  );
  updateStateFromPayload(data);
}

function connectRoomSocket() {
  if (!state.roomId || !state.participantId) {
    return;
  }

  if (roomSocket && roomSocket.readyState === WebSocket.OPEN) {
    return;
  }

  if (roomSocket) {
    roomSocket.close();
  }

  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const url = `${protocol}//${window.location.host}${basePath}/ws/rooms/${state.roomId}?participantId=${encodeURIComponent(state.participantId)}`;

  roomSocket = new WebSocket(url);
  roomSocket.addEventListener("message", (event) => {
    updateStateFromPayload(JSON.parse(event.data));
  });
  roomSocket.addEventListener("close", () => {
    if (state.roomId && state.participantId) {
      window.setTimeout(() => {
        if (roomSocket && roomSocket.readyState === WebSocket.CLOSED) {
          connectRoomSocket();
        }
      }, pollIntervalMs);
    }
  });
}

async function createRoom(name) {
  const data = await api("/api/rooms", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
  state.roomId = data.roomId;
  state.participantId = data.participantId;
  state.room = data.room;
  state.viewer = {
    participantId: data.participantId,
    isLeader: true,
    name,
    currentVote: null,
  };
  persistParticipant();
  window.history.replaceState({}, "", `${basePath}/room/${state.roomId}`);
  render();
  connectRoomSocket();
}

async function joinRoom(name) {
  const data = await api(`/api/rooms/${state.roomId}/join`, {
    method: "POST",
    body: JSON.stringify({ name }),
  });
  state.participantId = data.participantId;
  state.room = data.room;
  state.viewer = {
    participantId: data.participantId,
    isLeader: false,
    name,
    currentVote: null,
  };
  persistParticipant();
  render();
  connectRoomSocket();
}

async function leaderAction(path) {
  try {
    clearMessage();
    const data = await api(`/api/rooms/${state.roomId}/${path}`, {
      method: "POST",
      body: JSON.stringify({ participantId: state.participantId }),
    });
    state.room = data.room;
    render();
  } catch (error) {
    setMessage(error.message, true);
  }
}

createForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(createForm);
  try {
    clearMessage();
    await createRoom((formData.get("name") || "").toString().trim());
  } catch (error) {
    setMessage(error.message, true);
  }
});

joinForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(joinForm);
  try {
    clearMessage();
    await joinRoom((formData.get("name") || "").toString().trim());
  } catch (error) {
    setMessage(error.message, true);
  }
});

startButton.addEventListener("click", () => leaderAction("start"));
revealButton.addEventListener("click", () => leaderAction("reveal"));
themeToggle.addEventListener("click", () => {
  applyTheme(currentTheme === "dark" ? "light" : "dark");
});
copyRoomLinkButton.addEventListener("click", async () => {
  try {
    await copyText(roomLink.href);
    setMessage("Room link copied");
  } catch {
    setMessage("Could not copy room link", true);
  }
});

renderVoteOptions();
applyTheme(currentTheme);
restoreParticipant();
render();

if (state.roomId && state.participantId) {
  refreshRoom().catch((error) => {
    localStorage.removeItem(roomStorageKey(state.roomId));
    state.participantId = null;
    setMessage(error.message, true);
    render();
  });
  connectRoomSocket();
}
