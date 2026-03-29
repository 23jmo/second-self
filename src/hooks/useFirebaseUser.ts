"use client";

import { useState, useEffect } from "react";
import { onAuthStateChanged, type User } from "firebase/auth";
import { auth } from "@/lib/firebase";

export function useFirebaseUser() {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    return onAuthStateChanged(auth, (u) => {
      setUser(u);
      setIsLoading(false);
    });
  }, []);

  return { user, isLoading };
}
