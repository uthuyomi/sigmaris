import Stripe from "stripe";

export const PRO_MONTHLY_PRICE_JPY = 980;

export const hasStripeConfig = () =>
  Boolean(process.env.STRIPE_SECRET_KEY && process.env.STRIPE_PRO_PRICE_ID);

export const getStripe = () => {
  if (!process.env.STRIPE_SECRET_KEY) {
    throw new Error("STRIPE_SECRET_KEY is not configured.");
  }

  return new Stripe(process.env.STRIPE_SECRET_KEY);
};

export const getProPriceId = () => {
  if (!process.env.STRIPE_PRO_PRICE_ID) {
    throw new Error("STRIPE_PRO_PRICE_ID is not configured.");
  }

  return process.env.STRIPE_PRO_PRICE_ID;
};
