import { AccessToken, AccessTokenOptions, VideoGrant } from "livekit-server-sdk";
import { NextResponse, NextRequest } from "next/server";

const API_KEY = process.env.LIVEKIT_API_KEY;
const API_SECRET = process.env.LIVEKIT_API_SECRET;
const LIVEKIT_URL = process.env.NEXT_PUBLIC_LIVEKIT_URL;

export const revalidate = 0;

export async function GET(request: NextRequest) {
  try {
    if (!LIVEKIT_URL || !API_KEY || !API_SECRET) {
      throw new Error("Missing LiveKit environment variables");
    }

    // 1. Get query parameters from the URL
    const searchParams = request.nextUrl.searchParams;
    const language = searchParams.get("language") || "hi";
    const voice = searchParams.get("voice") || "sarvam";

    const participantIdentity = `user_${Math.floor(Math.random() * 10_000)}`;
    const roomName = `room_${Math.floor(Math.random() * 10_000)}`;

    // 2. Create metadata JSON string
    const metadata = JSON.stringify({
      language: language,
      voice: voice,
    });

    const participantToken = await createParticipantToken(
      { identity: participantIdentity, metadata: metadata }, // Pass metadata here
      roomName
    );

    const data = {
      serverUrl: LIVEKIT_URL,
      roomName,
      participantToken: participantToken,
      participantName: participantIdentity,
    };

    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof Error) {
      console.error(error);
      return new NextResponse(error.message, { status: 500 });
    }
  }
}

function createParticipantToken(userInfo: AccessTokenOptions, roomName: string) {
  const at = new AccessToken(API_KEY, API_SECRET, {
    ...userInfo,
    ttl: "15m",
  });
  const grant: VideoGrant = {
    room: roomName,
    roomJoin: true,
    canPublish: true,
    canPublishData: true,
    canSubscribe: true,
  };
  at.addGrant(grant);
  return at.toJwt();
}