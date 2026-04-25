// 役割: OpenAI APIクライアントの生成と共通設定をまとめる。

import OpenAI from "openai";

export const hasOpenAIConfig = () => Boolean(process.env.OPENAI_API_KEY);

export const getOpenAIClient = () => {
  if (!process.env.OPENAI_API_KEY) {
    throw new Error("OPENAI_API_KEY is not set.");
  }

  return new OpenAI({
    apiKey: process.env.OPENAI_API_KEY,
  });
};
