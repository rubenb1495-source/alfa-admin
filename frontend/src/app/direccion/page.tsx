"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function RedireccionDireccion() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/dashboard/direccion");
  }, [router]);
  return null;
}
