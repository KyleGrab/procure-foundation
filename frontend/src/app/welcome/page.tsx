import { HomeGateway } from "@/components/gateway/HomeGateway";
import { resolveClientBrand } from "@/lib/branding";

// Brand resolution now lives in lib/branding.ts (one function, reusable by any future page),
// not inlined here - this page's only job is rendering the gateway with whatever brand that
// layer resolves to.
export default function WelcomePage() {
  return <HomeGateway clientBrand={resolveClientBrand()} />;
}
