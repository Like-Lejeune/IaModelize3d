import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import "@fontsource-variable/bricolage-grotesque/index.css";
import "@fontsource/atkinson-hyperlegible/400.css";
import "@fontsource/atkinson-hyperlegible/700.css";
import "./styles.css";
import App from "./App";

// The API makes an anonymous session on a visitor's first call and sets its cookie. Calls sent in parallel before
// that cookie exists would each get a different session (a project made by one, its message refused for the other):
// the session is opened first, then the app starts.
fetch("/api/shop/me", { credentials: "same-origin" })
  .catch(() => undefined)
  .finally(() =>
    createRoot(document.getElementById("root")!).render(
      <StrictMode>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </StrictMode>,
    ),
  );
