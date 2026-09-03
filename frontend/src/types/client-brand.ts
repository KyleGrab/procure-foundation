export interface ClientBrand {
  name: string;
  primaryColor: string;
  logoUrl?: string;
  logoAlt?: string;
  truckImageSrc?: string;
  workerImageSrc?: string;
}

export const DEFAULT_CLIENT_BRAND: ClientBrand = {
  name: "ProcureIQ",
  primaryColor: "#6366F1", // matches the rest of the app's indigo accent, not an arbitrary new color
};
