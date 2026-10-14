import { createContext } from "react";

export const UiCtx = createContext({ toast: () => {}, confirm: () => {} });
