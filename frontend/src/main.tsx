import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./styles.css";
import { initHrlI18n } from "./lib/hrl/hrl-i18n";
import { PAIRS } from "./lib/hrl/dict";

// English is the main language; Polish via the switcher, ?lang=pl or the shared hrl_lang cookie.
initHrlI18n({ pairs: PAIRS, storageKey: "books_lang" });

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
