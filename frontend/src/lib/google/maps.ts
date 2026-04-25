// 役割: Google Maps APIを使った経路や地点情報の取得処理をまとめる。

export type TravelMode = "bicycle" | "car" | "walk";
export type SurfaceTravelMode = TravelMode;

export const hasGoogleMapsConfig = () => Boolean(process.env.GOOGLE_MAPS_API_KEY);
