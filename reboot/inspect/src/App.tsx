import { useState } from "react";
import { useSessions, useSession } from "../api/rbt/mcp/v1/session_rbt_react";
import { useStream } from "../api/rbt/mcp/v1/stream_rbt_react";
import Mermaid from "./Mermaid";

function messagesToSequenceDiagram(messages: any[]): string {
  console.log(messages);
  let diagram = "sequenceDiagram\n";
  diagram += "    participant Client as MCP Client\n";
  diagram += "    participant Server as MCP Server\n\n";

  for (const msg of messages) {
    let label = "unknown";

    if (msg.message?.method) {
      label = msg.message.method;
    } else if (msg.message?.result) {
      const result = msg.message.result;
      if (result.capabilities) {
        label = "capabilities";
      } else if (result.tools) {
        label = "tools";
      } else if (result.prompts) {
        label = "prompts";
      } else if (result.action) {
        label = `action: ${result.action}`;
      } else if (result.content && Array.isArray(result.content)) {
        const textParts = result.content
          .map((item: any) => item.text)
          .filter((text: any) => text !== undefined);
        label = `result: ${textParts.join(" ")}`;
      }
    }

    const isResponse = msg.eventId !== undefined;

    if (isResponse) {
      // Response from server to client
      diagram += `    Server->>Client: ${label}\n`;
    } else {
      // Request from client to server
      diagram += `    Client->>Server: ${label}\n`;
    }
  }

  return diagram;
}

function StreamSequenceDiagram({
  selectedStreamId,
}: {
  selectedStreamId: string;
}) {
  const { useMessages } = useStream({
    id: selectedStreamId,
  });
  const { response } = useMessages();

  const messages = response
    ? response.messages.map((msg: any) => msg.toJson())
    : [];

  return (
    <>
      <div className="w-1 min-w-1 bg-[#444] cursor-col-resize relative flex-shrink-0 h-full transition-colors hover:bg-[#555] active:bg-[#007bff]" />
      <div className="bg-[#2c2c2c] flex flex-col overflow-hidden flex-1 min-w-[400px]">
        <div className="bg-[#383838] text-white m-0 px-4 text-sm font-bold uppercase tracking-wider border-b border-[#444] h-[41px] flex items-center">
          Sequence Diagram
        </div>
        <div className="flex-1 overflow-y-auto overflow-x-auto p-4">
          {!selectedStreamId ? (
            <div className="flex items-center justify-center h-full text-[#a0a0a0] italic">
              Select a stream to view sequence diagram
            </div>
          ) : (
            <div className="flex items-center justify-center h-full text-[#a0a0a0] italic">
              <Mermaid chart={messagesToSequenceDiagram(messages)} />
            </div>
          )}
        </div>
      </div>
    </>
  );
}

function StreamView({ selectedSessionId }: { selectedSessionId: string }) {
  const { useGet } = useSession({ id: selectedSessionId });
  const { response } = useGet();
  const [selectedStreamId, setSelectedStreamId] = useState<string | null>(null);

  const streamIds = response ? response.streamIds.sort() : [];

  return (
    <>
      <div className="w-1 min-w-1 bg-[#444] cursor-col-resize relative flex-shrink-0 h-full transition-colors hover:bg-[#555] active:bg-[#007bff]" />

      <div className="bg-[#2c2c2c] flex flex-col overflow-hidden flex-shrink-0 min-w-[200px]">
        <div className="bg-[#383838] text-white m-0 px-4 text-sm font-bold uppercase tracking-wider border-b border-[#444] h-[41px] flex items-center">
          Request ID
        </div>
        <div className="flex-1 overflow-y-auto overflow-x-auto [&::-webkit-scrollbar]:w-2 [&::-webkit-scrollbar-track]:bg-[#333] [&::-webkit-scrollbar-thumb]:bg-[#555] [&::-webkit-scrollbar-thumb]:rounded [&::-webkit-scrollbar-thumb:hover]:bg-[#666]">
          {streamIds.length === 0 ? (
            <div className="p-5 px-4 text-[#a0a0a0] italic text-center">
              No streams found
            </div>
          ) : (
            streamIds.map((streamId) => (
              <div
                key={streamId}
                className={`px-4 py-2.5 cursor-pointer border-b border-[#333] font-mono text-[13px] transition-colors whitespace-nowrap min-w-fit hover:bg-[#404040] ${
                  selectedStreamId === streamId
                    ? "bg-[#007bff] text-white hover:bg-[#0056b3]"
                    : "text-[#e0e0e0]"
                }`}
                onClick={() => setSelectedStreamId(streamId)}
              >
                {streamId.split("/").pop()}
              </div>
            ))
          )}
        </div>
      </div>
      {selectedStreamId && (
        <StreamSequenceDiagram selectedStreamId={selectedStreamId} />
      )}
    </>
  );
}

function SessionsView({ sessionIds }: { sessionIds: string[] }) {
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(
    null
  );

  return (
    <div className="flex h-screen bg-[#2c2c2c] relative">
      <div className="bg-[#2c2c2c] flex flex-col overflow-hidden flex-shrink-0 min-w-[200px]">
        <div className="bg-[#383838] text-white m-0 px-4 text-sm font-bold uppercase tracking-wider border-b border-[#444] h-[41px] flex items-center">
          Session
        </div>
        <div className="flex-1 overflow-y-auto overflow-x-auto [&::-webkit-scrollbar]:w-2 [&::-webkit-scrollbar-track]:bg-[#333] [&::-webkit-scrollbar-thumb]:bg-[#555] [&::-webkit-scrollbar-thumb]:rounded [&::-webkit-scrollbar-thumb:hover]:bg-[#666]">
          {sessionIds.length === 0 ? (
            <div className="p-5 px-4 text-[#a0a0a0] italic text-center">
              No sessions found
            </div>
          ) : (
            sessionIds.map((sessionId) => (
              <div
                key={sessionId}
                className={`px-4 py-2.5 cursor-pointer border-b border-[#333] font-mono text-[13px] transition-colors whitespace-nowrap min-w-fit hover:bg-[#404040] ${
                  selectedSessionId === sessionId
                    ? "bg-[#007bff] text-white hover:bg-[#0056b3]"
                    : "text-[#e0e0e0]"
                }`}
                onClick={() => setSelectedSessionId(sessionId)}
              >
                {sessionId}
              </div>
            ))
          )}
        </div>
      </div>
      {selectedSessionId !== null && (
        <StreamView selectedSessionId={selectedSessionId} />
      )}
    </div>
  );
}

function App() {
  const { useList } = useSessions({
    id: "reboot-dev-durable-mcp-sessions-index",
  });
  // TODO: implement pagination.
  const { response } = useList({ limit: 500 });

  if (response === undefined) {
    return (
      <div className="flex h-screen bg-[#2c2c2c]">
        <div className="p-5 text-[#a0a0a0] italic text-center">
          Loading sessions...
        </div>
      </div>
    );
  }

  return <SessionsView sessionIds={response.sessionIds} />;
}

export default App;
