const voteOptions = [1, 2, 3, 5, 8, 13, 21];
const pollIntervalMs = 2000;

const state = {
  roomId: window.location.pathname.startsWith("/room/")
    ? window.location.pathname.split("/").pop()
    : null,
  participantId: null,
  room: null,
  viewer: null,
};
let roomSocket = null;

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
const viewerLabel = document.querySelector("#viewer-label");
const voteStatus = document.querySelector("#vote-status");
const avgValue = document.querySelector("#avg-value");
const medianValue = document.querySelector("#median-value");
const modeValue = document.querySelector("#mode-value");
const leaderActions = document.querySelector("#leader-actions");
const messageNode = document.querySelector("#message");

const startButton = document.querySelector("#start-button");
const revealButton = document.querySelector("#reveal-button");
const restartButton = document.querySelector("#restart-button");

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

function updateStateFromPayload(payload) {
  state.room = payload.room;
  state.viewer = payload.viewer;
  render();
}

async function api(path, options = {}) {
  const response = await fetch(path, {
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
  state.room.participants.forEach((participant) => {
    const item = document.createElement("article");
    item.className = "participant-card";

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

    item.appendChild(title);
    item.appendChild(labelNode);
    item.appendChild(meta);
    participantsNode.appendChild(item);
  });
}

function renderStats() {
  const stats = state.room.stats;
  const visible = state.room.phase === "revealed" && stats;
  statsPanel.classList.toggle("hidden", !visible);
  if (!visible) {
    return;
  }

  avgValue.textContent = String(stats.average);
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
  restartButton.disabled = state.room.phase !== "revealed";
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
    joinForm.classList.toggle("hidden", !state.roomId);
    return;
  }

  authView.classList.add("hidden");
  roomView.classList.remove("hidden");

  phaseBadge.textContent = formatPhase(state.room.phase);
  roomLink.textContent = `${window.location.origin}/room/${state.roomId}`;
  roomLink.href = roomLink.textContent;
  viewerLabel.textContent = state.viewer?.name
    ? `${state.viewer.name}${state.viewer.isLeader ? " (leader)" : ""}`
    : "";

  renderParticipants();
  renderLeaderControls();
  renderVotePanel();
  renderStats();
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
  const url = `${protocol}//${window.location.host}/ws/rooms/${state.roomId}?participantId=${encodeURIComponent(state.participantId)}`;

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
  window.history.replaceState({}, "", `/room/${state.roomId}`);
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
restartButton.addEventListener("click", () => leaderAction("restart"));

renderVoteOptions();
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
