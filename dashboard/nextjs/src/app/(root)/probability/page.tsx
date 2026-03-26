import { permanentRedirect } from "next/navigation";

export default function ProbabilityAliasPage() {
  permanentRedirect("/analysis?tab=probability");
}
