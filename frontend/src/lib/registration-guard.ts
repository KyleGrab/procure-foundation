/**
 * D-01: pure guard controlling whether the "Register organisation" link renders on the landing
 * page. This is UX only, exactly as scoped - the actual control is the backend's
 * RegistrationDisabledError (app/services/auth_service.py), which fires regardless of whether
 * this link is visible. Hiding a link a determined visitor could still navigate to directly
 * would be a false sense of security if this were the only gate; it isn't.
 *
 * Defaults to visible (true) when unset - production behaviour is unchanged unless a deployment
 * deliberately sets NEXT_PUBLIC_ALLOW_SELF_REGISTRATION to exactly "false". Same precise,
 * no-partial-match discipline as dev-demo-guard.ts's shouldShowDevDemoLogin.
 */

export function shouldShowRegistrationLink(allowSelfRegistration: string | undefined): boolean {
  return allowSelfRegistration !== "false";
}
