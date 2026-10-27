/** Warms one picture in the browser cache, so a later screen can show it without a wait. */
export function preloadImage(url: string) {
  new Image().src = url;
}
