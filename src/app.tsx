import { PipecatClient, RTVIEvent } from "@pipecat-ai/client-js";
import { WebSocketTransport } from "@pipecat-ai/websocket-transport";
import { useCallback, useEffect, useRef, useState } from "react";
import "./voice.css";

// Backend URL — configurable via env
const BACKEND_URL =
  import.meta.env["VITE_BACKEND_URL"] ?? "http://localhost:8001";

// Unison API URL + token for the in-browser whoami check
const UNISON_API_URL =
  import.meta.env["VITE_UNISON_API_URL"] ?? "https://api.unisonlabs.ai";
const UNISON_TOKEN = import.meta.env["VITE_UNISON_TOKEN"] ?? "";

// ── Logos ──────────────────────────────────────────────────────────────────

const UnisonWordmark = ({ className }: { className?: string }) => (
  <svg
    className={className}
    fill="none"
    viewBox="0 0 120 28"
    xmlns="http://www.w3.org/2000/svg"
    aria-label="Unison"
  >
    <title>Unison</title>
    <text
      x="0"
      y="22"
      fontSize="22"
      fontWeight="600"
      fontFamily="'Inter', system-ui, sans-serif"
      fill="currentColor"
      letterSpacing="-0.5"
    >
      Unison
    </text>
  </svg>
);

const PipecatWordmark = ({ className }: { className?: string }) => (
  <svg
    className={className}
    fill="none"
    viewBox="0 0 100 28"
    xmlns="http://www.w3.org/2000/svg"
    aria-label="Pipecat"
  >
    <title>Pipecat</title>
    <text
      x="0"
      y="22"
      fontSize="22"
      fontWeight="400"
      fontFamily="'Inter', system-ui, sans-serif"
      fill="currentColor"
      letterSpacing="-0.5"
    >
      Pipecat
    </text>
  </svg>
);

const IntegrationHeader = ({ className }: { className?: string }) => (
  <div className={`integration-header ${className ?? ""}`}>
    <UnisonWordmark className="unison-wordmark" />
    <span className="divider">×</span>
    <PipecatWordmark className="pipecat-wordmark" />
  </div>
);

// ── Types ──────────────────────────────────────────────────────────────────

interface Memory {
  id: string;
  memory: string;
  path: string;
  score?: number;
  created_at: string;
  type: string;
}

interface ProfileData {
  profile: {
    static: string[];
    dynamic: string[];
  };
}

interface SessionDocument {
  id: string;
  title: string;
  summary: string;
  createdAt: string;
  path: string;
}

interface TranscriptEntry {
  role: "user" | "bot";
  text: string;
  timestamp: Date;
}

// ── Unison brain client helpers ────────────────────────────────────────────

async function searchMemories(
  userId: string,
  query?: string,
): Promise<Memory[]> {
  const params = new URLSearchParams({ userId });
  if (query) params.set("query", query);
  const resp = await fetch(`${BACKEND_URL}/api/memories?${params}`);
  if (!resp.ok) return [];
  const data = (await resp.json()) as { memories?: Memory[]; error?: string };
  if (data.error || !Array.isArray(data.memories)) return [];
  return data.memories;
}

async function fetchProfileData(userId: string): Promise<ProfileData | null> {
  try {
    const resp = await fetch(`${BACKEND_URL}/api/profile?userId=${userId}`);
    if (!resp.ok) return null;
    const data = (await resp.json()) as ProfileData & { error?: string };
    if (data.error || !data.profile) return null;
    return data;
  } catch {
    return null;
  }
}

async function fetchSessionDocuments(
  userId: string,
  limit = 10,
): Promise<SessionDocument[]> {
  try {
    const resp = await fetch(
      `${BACKEND_URL}/api/documents?userId=${userId}&page=1&limit=${limit}`,
    );
    if (!resp.ok) return [];
    const data = (await resp.json()) as {
      documents?: SessionDocument[];
      error?: string;
    };
    if (data.error || !Array.isArray(data.documents)) return [];
    return data.documents;
  } catch {
    return [];
  }
}

async function checkWhoami(): Promise<{
  email: string;
  tenant: string;
} | null> {
  if (!UNISON_TOKEN) return null;
  try {
    const resp = await fetch(`${UNISON_API_URL}/v1/auth/whoami`, {
      headers: { Authorization: `Bearer ${UNISON_TOKEN}` },
    });
    if (!resp.ok) return null;
    const data = (await resp.json()) as {
      user?: { email?: string };
      tenant?: { name?: string };
    };
    return {
      email: data.user?.email ?? "",
      tenant: data.tenant?.name ?? "",
    };
  } catch {
    return null;
  }
}

// ── Main app ───────────────────────────────────────────────────────────────

export function VoiceApp() {
  // Stable userId (persists across page reloads)
  const [userId] = useState(() => {
    const stored = localStorage.getItem("pipecat-unison-userId");
    if (stored) return stored;
    const id = `user-${Math.random().toString(36).substring(2, 15)}`;
    localStorage.setItem("pipecat-unison-userId", id);
    return id;
  });

  const [sessionId] = useState(
    () => `session-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`,
  );

  // Connection state
  const [hasEverStarted, setHasEverStarted] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [isBotReady, setIsBotReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Brain auth status
  const [whoami, setWhoami] = useState<{
    email: string;
    tenant: string;
  } | null>(null);

  // Transcript
  const [transcripts, setTranscripts] = useState<TranscriptEntry[]>([]);

  // Memories panel
  const [memories, setMemories] = useState<Memory[]>([]);
  const [isLoadingMemories, setIsLoadingMemories] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  // Profile + session docs
  const [profileData, setProfileData] = useState<ProfileData | null>(null);
  const [sessionDocs, setSessionDocs] = useState<SessionDocument[]>([]);

  // Active right-panel tab
  const [activeTab, setActiveTab] = useState<"context" | "sessions">("context");

  // Refs
  const clientRef = useRef<PipecatClient | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const ttsBufferRef = useRef<string>("");
  const lastBotMsgIdxRef = useRef<number>(-1);

  // Verify brain connection on mount
  useEffect(() => {
    checkWhoami().then(setWhoami);
  }, []);

  // Auto-scroll to the bottom whenever transcripts change.
  // biome-ignore lint/correctness/useExhaustiveDependencies: scroll when transcripts.length changes
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [transcripts.length]);

  const addTranscript = useCallback((role: "user" | "bot", text: string) => {
    setTranscripts((prev) => [...prev, { role, text, timestamp: new Date() }]);
  }, []);

  const setupAudioTrack = useCallback((track: MediaStreamTrack) => {
    if (!audioRef.current) return;
    const stream = new MediaStream([track]);
    audioRef.current.srcObject = stream;
    audioRef.current.play().catch(console.error);
  }, []);

  // Fetch memories from the backend (which proxies to Unison)
  const fetchMemories = useCallback(
    async (query?: string, showLoading = true) => {
      if (showLoading) setIsLoadingMemories(true);
      try {
        const result = await searchMemories(userId, query || undefined);
        if (result.length > 0 || query) {
          setMemories(result);
        }
      } catch (err) {
        console.error("Failed to fetch memories:", err);
      }
      if (showLoading) setIsLoadingMemories(false);
    },
    [userId],
  );

  // Fetch profile (preserves existing data on error)
  const fetchProfile = useCallback(async () => {
    const data = await fetchProfileData(userId);
    if (data) setProfileData(data);
  }, [userId]);

  // Fetch session documents (preserves existing data on error)
  const fetchSessionDocs = useCallback(async () => {
    const docs = await fetchSessionDocuments(userId, 10);
    if (docs.length > 0) setSessionDocs(docs);
  }, [userId]);

  // Staggered polling for context tab data
  useEffect(() => {
    if (!hasEverStarted || activeTab !== "context") return;

    fetchMemories(searchQuery || undefined, true);
    const t1 = setTimeout(() => fetchProfile(), 400);
    const t2 = setTimeout(() => fetchSessionDocs(), 800);

    const intervalMemories = setInterval(
      () => fetchMemories(searchQuery || undefined, false),
      10000,
    );
    const intervalProfile = setInterval(() => fetchProfile(), 12000);
    const intervalSessions = setInterval(() => fetchSessionDocs(), 14000);

    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
      clearInterval(intervalMemories);
      clearInterval(intervalProfile);
      clearInterval(intervalSessions);
    };
  }, [
    hasEverStarted,
    activeTab,
    fetchMemories,
    fetchProfile,
    fetchSessionDocs,
    searchQuery,
  ]);

  // Polling for sessions tab
  useEffect(() => {
    if (!hasEverStarted || activeTab !== "sessions") return;

    fetchSessionDocs();
    const interval = setInterval(() => fetchSessionDocs(), 10000);
    return () => clearInterval(interval);
  }, [hasEverStarted, activeTab, fetchSessionDocs]);

  // ── Voice connection ──────────────────────────────────────────────────────

  const startConversation = useCallback(async () => {
    setHasEverStarted(true);
    setIsConnecting(true);
    setError(null);

    try {
      const client = new PipecatClient({
        transport: new WebSocketTransport(),
        enableMic: true,
        enableCam: false,
        callbacks: {
          onConnected: () => {
            setIsConnected(true);
            setIsConnecting(false);
          },
          onDisconnected: () => {
            setIsConnected(false);
            setIsBotReady(false);
          },
          onBotReady: () => {
            setIsBotReady(true);
          },
          onBotStartedSpeaking: () => {
            // Mute mic while bot speaks to prevent echo
            client.enableMic(false);
          },
          onBotStoppedSpeaking: () => {
            client.enableMic(true);
          },
          onUserTranscript: (data) => {
            if (data.final) {
              ttsBufferRef.current = "";
              lastBotMsgIdxRef.current = -1;
              addTranscript("user", data.text);
              // Refresh memories + profile 3 s after the user speaks
              setTimeout(() => {
                fetchMemories(undefined, false);
                fetchProfile();
              }, 3000);
            }
          },
          onBotTtsText: (data) => {
            const chunk = data.text ?? "";
            ttsBufferRef.current += chunk;

            setTranscripts((prev) => {
              const next = [...prev];
              if (
                lastBotMsgIdxRef.current >= 0 &&
                lastBotMsgIdxRef.current < next.length
              ) {
                next[lastBotMsgIdxRef.current] = {
                  ...next[lastBotMsgIdxRef.current],
                  text: ttsBufferRef.current,
                };
              } else {
                lastBotMsgIdxRef.current = next.length;
                next.push({
                  role: "bot",
                  text: ttsBufferRef.current,
                  timestamp: new Date(),
                });
              }
              return next;
            });
          },
          onError: (msg) => {
            console.error("PipecatClient error:", msg);
            const detail =
              typeof msg.data === "object" &&
              msg.data !== null &&
              "message" in msg.data
                ? String((msg.data as { message: string }).message)
                : String(msg.type ?? "Connection error");
            setError(detail);
          },
        },
      });

      clientRef.current = client;

      client.on(RTVIEvent.TrackStarted, (track, participant) => {
        if (!participant?.local && track.kind === "audio") {
          setupAudioTrack(track);
        }
      });

      await client.initDevices();

      const connectUrl = `${BACKEND_URL}/connect?userId=${userId}&sessionId=${sessionId}`;
      await client.startBotAndConnect({ endpoint: connectUrl });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to connect";
      console.error("Connection failed:", err);
      setError(msg);
      setIsConnecting(false);
      clientRef.current = null;
    }
  }, [
    addTranscript,
    setupAudioTrack,
    fetchMemories,
    fetchProfile,
    userId,
    sessionId,
  ]);

  const endConversation = useCallback(async () => {
    if (clientRef.current) {
      await clientRef.current.disconnect();
      clientRef.current = null;
    }
    setIsConnected(false);
    setIsBotReady(false);
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      clientRef.current?.disconnect();
    };
  }, []);

  const formatRelativeTime = (dateStr: string) => {
    if (!dateStr) return "";
    const date = new Date(dateStr);
    const diff = Date.now() - date.getTime();
    const mins = Math.floor(diff / 60_000);
    const hours = Math.floor(diff / 3_600_000);
    const days = Math.floor(diff / 86_400_000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}m ago`;
    if (hours < 24) return `${hours}h ago`;
    return `${days}d ago`;
  };

  // ── Landing view ──────────────────────────────────────────────────────────

  if (!hasEverStarted) {
    return (
      <div className="landing-container">
        {/* biome-ignore lint/a11y/useMediaCaption: voice bot audio stream has no captions */}
        <audio autoPlay ref={audioRef} />
        <IntegrationHeader />
        <div className="start-button-section">
          <button
            className="gradient-circle"
            disabled={isConnecting}
            onClick={startConversation}
            type="button"
            aria-label="Start conversation"
          />
          <span className="start-text">[ start conversation ]</span>
        </div>
        <div className="user-info">
          <span>User ID: {userId}</span>
          {whoami && (
            <span className="brain-status">
              Brain: {whoami.tenant || whoami.email}
            </span>
          )}
          {!UNISON_TOKEN && (
            <span className="brain-warning">
              VITE_UNISON_TOKEN not set — memory panel will be empty
            </span>
          )}
        </div>
        {error && <div className="error-banner">{error}</div>}
      </div>
    );
  }

  // ── Conversation view ─────────────────────────────────────────────────────

  return (
    <div className="app-container">
      {/* biome-ignore lint/a11y/useMediaCaption: voice bot audio stream has no captions */}
      <audio autoPlay ref={audioRef} />

      {/* Left panel — transcript */}
      <div className="left-panel">
        <div className="top-bar">
          <IntegrationHeader className="top-bar-logo" />
        </div>

        <div className="conversation-control-bar">
          <div className="gradient-circle-small" />
          <span className="control-bar-text">
            {isConnecting
              ? "[ connecting... ]"
              : isBotReady
                ? "[ recording conversation ]"
                : "[ start conversation ]"}
          </span>
          {!isConnected && !isConnecting && (
            <button
              className="start-btn-inline"
              onClick={startConversation}
              type="button"
            >
              Start
            </button>
          )}
          {(isConnected || isBotReady) && (
            <button className="end-btn" onClick={endConversation} type="button">
              End
            </button>
          )}
        </div>

        <div className="messages-area">
          {transcripts.length === 0 && !isConnecting ? (
            <div className="empty-messages">
              <span>Waiting for conversation...</span>
            </div>
          ) : (
            <>
              {transcripts.map((entry) => (
                <div
                  className={`message ${entry.role}`}
                  key={`${entry.role}-${entry.timestamp.getTime()}`}
                >
                  <div className="message-role">
                    {entry.role === "user" ? "You" : "AI"}
                  </div>
                  {entry.text}
                </div>
              ))}
              <div ref={messagesEndRef} />
            </>
          )}
        </div>

        {error && <div className="error-banner">{error}</div>}
      </div>

      {/* Right panel — Unison brain */}
      <div className="right-panel">
        <div className="tabs-header">
          <button
            className={`tab-button ${activeTab === "context" ? "active" : ""}`}
            onClick={() => setActiveTab("context")}
            type="button"
          >
            Context
          </button>
          <button
            className={`tab-button ${activeTab === "sessions" ? "active" : ""}`}
            onClick={() => setActiveTab("sessions")}
            type="button"
          >
            Sessions
          </button>
          {whoami && (
            <span className="brain-tenant">
              {whoami.tenant || whoami.email}
            </span>
          )}
        </div>

        <div className="tab-content">
          {activeTab === "context" && (
            <div className="context-two-column">
              {/* Left column — Memories */}
              <div className="context-column memories-column">
                <div className="column-header">
                  <h3 className="column-title">Memories</h3>
                </div>

                <div className="search-bar">
                  <input
                    className="search-input"
                    placeholder="Search memories..."
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter")
                        fetchMemories(searchQuery || undefined);
                    }}
                  />
                  <button
                    className="search-btn"
                    type="button"
                    onClick={() => fetchMemories(searchQuery || undefined)}
                  >
                    Search
                  </button>
                </div>

                {isLoadingMemories && memories.length === 0 ? (
                  <div className="loading">
                    <div className="loading-spinner" />
                    Loading...
                  </div>
                ) : memories.length === 0 ? (
                  <div className="empty-state">
                    <span>No memories yet</span>
                    <span>Start a conversation to generate memories</span>
                  </div>
                ) : (
                  <div className="memory-list">
                    {memories.map((mem) => (
                      <div className="memory-card" key={mem.id}>
                        <div className="memory-content">{mem.memory}</div>
                        <div className="memory-meta">
                          <span className="memory-path">{mem.path}</span>
                          {mem.created_at && (
                            <span className="memory-time">
                              {formatRelativeTime(mem.created_at)}
                            </span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Right column — Profile */}
              <div className="context-column profile-column">
                <div className="profile-section">
                  <div className="section-header">
                    <div className="section-indicator" />
                    <h3 className="section-title">Profile</h3>
                  </div>
                  <div className="profile-content">
                    {profileData?.profile.static &&
                      profileData.profile.static.length > 0 && (
                        <div className="profile-subsection">
                          <div className="subsection-label">Static</div>
                          <div className="profile-facts">
                            {profileData.profile.static.map((fact, idx) => (
                              <div
                                className="profile-fact static"
                                key={`static-${
                                  // biome-ignore lint/suspicious/noArrayIndexKey: stable ordered list
                                  idx
                                }`}
                              >
                                {fact}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    {profileData?.profile.dynamic &&
                      profileData.profile.dynamic.length > 0 && (
                        <div className="profile-subsection">
                          <div className="subsection-label">Dynamic</div>
                          <div className="profile-facts">
                            {profileData.profile.dynamic.map((fact, idx) => (
                              <div
                                className="profile-fact dynamic"
                                key={`dynamic-${
                                  // biome-ignore lint/suspicious/noArrayIndexKey: stable ordered list
                                  idx
                                }`}
                              >
                                {fact}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    {!profileData?.profile.static?.length &&
                      !profileData?.profile.dynamic?.length && (
                        <div className="empty-section">
                          <span>No profile data yet</span>
                        </div>
                      )}
                  </div>
                </div>
              </div>
            </div>
          )}

          {activeTab === "sessions" && (
            <div className="sessions-container">
              <div className="column-header">
                <h3 className="column-title">Past Sessions</h3>
              </div>
              {sessionDocs.length === 0 ? (
                <div className="empty-state">
                  <span>No sessions yet</span>
                  <span>Session notes are saved after each conversation</span>
                </div>
              ) : (
                <div className="session-docs">
                  {sessionDocs.map((doc) => (
                    <div className="session-doc" key={doc.id}>
                      <div className="session-doc-title">{doc.title}</div>
                      {doc.summary && (
                        <div className="session-doc-summary">{doc.summary}</div>
                      )}
                      <div className="session-doc-time">
                        {formatRelativeTime(doc.createdAt)}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        <div className="user-id-footer">
          <span>User: {userId}</span>
        </div>
      </div>
    </div>
  );
}
