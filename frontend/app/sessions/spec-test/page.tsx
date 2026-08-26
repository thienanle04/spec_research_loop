import { SpecConstructionWizard } from "@/features/spec/SpecConstructionWizard";

export default function SpecTestPage() {
  return (
    <main className="px-4 py-6 sm:px-6 max-w-4xl mx-auto">
      <h1 className="text-2xl font-serif text-navy mb-6">Spec Construction Test Playground</h1>
      <SpecConstructionWizard />
    </main>
  );
}
