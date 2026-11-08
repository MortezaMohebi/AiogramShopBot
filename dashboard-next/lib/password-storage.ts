type PasswordCredentialConstructor = new (data: { id: string; password: string }) => Credential;

/** Offer only a server-verified password; browser refusal never blocks login. */
export async function offerPasswordStorage(username: string, password: string): Promise<void> {
  const Constructor = (window as Window & { PasswordCredential?: PasswordCredentialConstructor }).PasswordCredential;
  if (!window.isSecureContext || !Constructor || !navigator.credentials?.store) return;
  let timer: number | undefined;
  try {
    const credential = new Constructor({ id: username, password });
    await Promise.race([
      navigator.credentials.store(credential),
      new Promise<void>(resolve => { timer = window.setTimeout(resolve, 1_200); }),
    ]);
  } catch {
    // Browser policy, unsupported stores and dismissal cannot undo authentication.
  } finally {
    if (timer !== undefined) window.clearTimeout(timer);
  }
}
