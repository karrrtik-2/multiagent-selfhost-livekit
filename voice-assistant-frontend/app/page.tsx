"use client";

import { CloseIcon } from "@/components/CloseIcon";
import { NoAgentNotification } from "@/components/NoAgentNotification";
import TranscriptionView from "@/components/TranscriptionView";
import {
  BarVisualizer,
  DisconnectButton,
  RoomAudioRenderer,
  RoomContext,
  VideoTrack,
  VoiceAssistantControlBar,
  useVoiceAssistant,
} from "@livekit/components-react";
import { AnimatePresence, motion } from "framer-motion";
import { Room, RoomEvent } from "livekit-client";
import { useCallback, useEffect, useState } from "react";

export default function Page() {
  const [room] = useState(new Room());
  // State for selections
  const [language, setLanguage] = useState("hi"); // 'hi' or 'en'
  const [voice, setVoice] = useState("sarvam");   // 'sarvam' or 'gemini'

  const onConnectButtonClicked = useCallback(async () => {
    // Pass selections as query parameters
    const url = new URL(
      process.env.NEXT_PUBLIC_CONN_DETAILS_ENDPOINT ?? "/api/connection-details",
      window.location.origin
    );
    url.searchParams.append("language", language);
    url.searchParams.append("voice", voice);

    const response = await fetch(url.toString());
    const connectionDetailsData = await response.json();

    await room.connect(connectionDetailsData.serverUrl, connectionDetailsData.participantToken);
    await room.localParticipant.setMicrophoneEnabled(true);
  }, [room, language, voice]);

  useEffect(() => {
    room.on(RoomEvent.MediaDevicesError, onDeviceFailure);
    return () => {
      room.off(RoomEvent.MediaDevicesError, onDeviceFailure);
    };
  }, [room]);

  return (
    <main data-lk-theme="default" className="h-full grid content-center bg-[var(--lk-bg)]">
      <RoomContext.Provider value={room}>
        <div className="lk-room-container max-w-[1024px] w-[90vw] mx-auto max-h-[90vh]">
          <SimpleVoiceAssistant 
            onConnectButtonClicked={onConnectButtonClicked}
            language={language}
            setLanguage={setLanguage}
            voice={voice}
            setVoice={setVoice}
          />
        </div>
      </RoomContext.Provider>
    </main>
  );
}

function SimpleVoiceAssistant(props: { 
  onConnectButtonClicked: () => void,
  language: string,
  setLanguage: (val: string) => void,
  voice: string,
  setVoice: (val: string) => void
}) {
  const { state: agentState } = useVoiceAssistant();

  return (
    <>
      <AnimatePresence mode="wait">
        {agentState === "disconnected" ? (
          <motion.div
            key="disconnected"
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            transition={{ duration: 0.3 }}
            className="grid items-center justify-center h-full gap-4 text-center"
          >
            {/* --- NEW UI: SELECTION DROPDOWNS --- */}
            <div className="flex flex-col gap-2 bg-white/10 p-4 rounded-lg">
              <label className="text-white text-sm">Language</label>
              <select 
                className="p-2 rounded text-black"
                value={props.language} 
                onChange={(e) => props.setLanguage(e.target.value)}
              >
                <option value="hi">Hindi (Nova-2)</option>
                <option value="en">English (Nova-2)</option>
              </select>

              <label className="text-white text-sm mt-2">Voice Model</label>
              <select 
                className="p-2 rounded text-black"
                value={props.voice} 
                onChange={(e) => props.setVoice(e.target.value)}
              >
                <option value="sarvam">Sarvam</option>
                <option value="gemini">Gemini (Google)</option>
              </select>
            </div>
            {/* ----------------------------------- */}

            <motion.button
              className="uppercase px-4 py-2 bg-white text-black rounded-md"
              onClick={() => props.onConnectButtonClicked()}
            >
              Start a conversation
            </motion.button>
          </motion.div>
        ) : (
          <motion.div
            key="connected"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            className="flex flex-col items-center gap-4 h-full"
          >
            <AgentVisualizer />
            <div className="flex-1 w-full">
              <TranscriptionView />
            </div>
            <div className="w-full">
              <ControlBar onConnectButtonClicked={props.onConnectButtonClicked} />
            </div>
            <RoomAudioRenderer />
            <NoAgentNotification state={agentState} />
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}

// ... (Keep AgentVisualizer, ControlBar, and onDeviceFailure exactly as they were) ...
function AgentVisualizer() {
    const { state: agentState, videoTrack, audioTrack } = useVoiceAssistant();
  
    if (videoTrack) {
      return (
        <div className="h-[512px] w-[512px] rounded-lg overflow-hidden">
          <VideoTrack trackRef={videoTrack} />
        </div>
      );
    }
    return (
      <div className="h-[300px] w-full">
        <BarVisualizer
          state={agentState}
          barCount={5}
          trackRef={audioTrack}
          className="agent-visualizer"
          options={{ minHeight: 24 }}
        />
      </div>
    );
  }
  
  function ControlBar(props: { onConnectButtonClicked: () => void }) {
    const { state: agentState } = useVoiceAssistant();
  
    return (
      <div className="relative h-[60px]">
        <AnimatePresence>
          {agentState === "disconnected" && (
            <motion.button
              initial={{ opacity: 0, top: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0, top: "-10px" }}
              transition={{ duration: 1, ease: [0.09, 1.04, 0.245, 1.055] }}
              className="uppercase absolute left-1/2 -translate-x-1/2 px-4 py-2 bg-white text-black rounded-md"
              onClick={() => props.onConnectButtonClicked()}
            >
              Start a conversation
            </motion.button>
          )}
        </AnimatePresence>
        <AnimatePresence>
          {agentState !== "disconnected" && agentState !== "connecting" && (
            <motion.div
              initial={{ opacity: 0, top: "10px" }}
              animate={{ opacity: 1, top: 0 }}
              exit={{ opacity: 0, top: "-10px" }}
              transition={{ duration: 0.4, ease: [0.09, 1.04, 0.245, 1.055] }}
              className="flex h-8 absolute left-1/2 -translate-x-1/2  justify-center"
            >
              <VoiceAssistantControlBar controls={{ leave: false }} />
              <DisconnectButton>
                <CloseIcon />
              </DisconnectButton>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    );
  }
  
  function onDeviceFailure(error: Error) {
    console.error(error);
    alert(
      "Error acquiring camera or microphone permissions. Please make sure you grant the necessary permissions in your browser and reload the tab"
    );
  }