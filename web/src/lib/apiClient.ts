import { client } from "../api/client.gen";

/** Flask serves the bundle and the API from one origin, so every request stays relative. */
client.setConfig({ baseUrl: "" });
