import { NextResponse } from "next/server";
import { isProBillingStatus, readBillingStatus } from "@/lib/billing";

export const requireProPlan = async (userId: string) => {
  const status = await readBillingStatus(userId);
  if (isProBillingStatus(status)) {
    return null;
  }

  return NextResponse.json(
    {
      error: "This feature requires シグマリス Pro.",
      code: "PRO_REQUIRED",
      billing: status,
    },
    { status: 402 },
  );
};
