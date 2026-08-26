import re

with open("frontend/features/loop/LoopSessionWorkbench.tsx", "r", encoding="utf-8") as f:
    content = f.read()

# 1. Add sticky top-6
content = content.replace(
    '<aside className="grid gap-4 lg:col-span-3 xl:col-span-3">',
    '<aside className="grid gap-4 lg:col-span-3 xl:col-span-3 lg:sticky lg:top-6">'
)

# 2. Add outer wrapping div and close it before the end of the return statement
before_return = """  return (
    <div className="mx-auto grid max-w-7xl grid-cols-1 gap-4 lg:grid-cols-12">"""

after_return = """  return (
  <div className="space-y-8 pb-12">
    <div className="mx-auto grid max-w-7xl grid-cols-1 gap-4 lg:grid-cols-12 lg:items-start">"""

content = content.replace(before_return, after_return)

# 3. Move DecisionHistory and ProducedSpecVersionView out of the right column
target_block = """          </section>
        <DecisionHistory
          decisions={
            decisionsQuery.data?.status === 200 ? decisionsQuery.data.data : []
          }
        />
        <ProducedSpecVersionView
          produced={session.produced_spec_version}
          validSpecVersionId={session.valid_spec_version_id}
        />
      </div>
    </div>
  );"""

new_block = """          </section>
      </div>
    </div>
    
    <div className="mx-auto max-w-7xl mt-4 grid gap-8 lg:px-0">
      <DecisionHistory
        decisions={
          decisionsQuery.data?.status === 200 ? decisionsQuery.data.data : []
        }
      />
      <ProducedSpecVersionView
        produced={session.produced_spec_version}
        validSpecVersionId={session.valid_spec_version_id}
      />
    </div>
  </div>
  );"""

content = content.replace(target_block, new_block)

# 4. Fix my previous `fix_workbench_confirm.py` which might have been wiped out by git checkout!
content = content.replace(
    """      const contributionComplete = workingDraftNode === WorkflowNode.contribution;
      setContinueTarget(
        contributionComplete ? null : continueTargetAfterConfirm(next, workingDraftNode),
      );
      setConfirmationMessage(
        contributionComplete
          ? "Saved."
          : "Saved. Select Continue to proceed to the next step.",
      );""",
    """      setContinueTarget(continueTargetAfterConfirm(next, workingDraftNode));
      setConfirmationMessage("Saved. Select Continue to proceed to the next step.");"""
)


with open("frontend/features/loop/LoopSessionWorkbench.tsx", "w", encoding="utf-8") as f:
    f.write(content)
