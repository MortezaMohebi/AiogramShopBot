import { redirect } from "next/navigation";

/** Never render an unauthenticated dashboard landing page. */
export default function Home() {
  redirect("/dashboard");
}
