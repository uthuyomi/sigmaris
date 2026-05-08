import { NextResponse } from "next/server";

export async function GET() {
  const publicKey = process.env.NEXT_PUBLIC_WEB_PUSH_PUBLIC_KEY;
  if (!publicKey) {
    return NextResponse.json({ error: "Web Push public key is not configured." }, { status: 503 });
  }

  return NextResponse.json({ publicKey });
}
