"use client";

import { createContext, useContext } from "react";
import type { Me } from "@/lib/types";

const UserContext = createContext<Me | null>(null);

export const UserProvider = UserContext.Provider;

export function useMe(): Me {
  const me = useContext(UserContext);
  if (!me) throw new Error("useMe must be used inside the authenticated layout");
  return me;
}
