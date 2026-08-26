import re

with open("frontend/features/loop/LoopSessionWorkbench.tsx", "r", encoding="utf-8") as f:
    content = f.read()

before_block = """          </section>
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
  );
}"""

after_block = """          </section>
      </div>
    </div>
    <div className="mx-auto max-w-7xl mt-8 grid gap-8 lg:px-0">
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
  );
}"""

content = content.replace(before_block, after_block)

before_return = """  return (
    <div className="mx-auto grid max-w-7xl grid-cols-1 gap-4 lg:grid-cols-12 lg:items-start">"""
after_return = """  return (
  <div className="space-y-8 pb-12 px-4 lg:px-8">
    <div className="mx-auto grid max-w-7xl grid-cols-1 gap-4 lg:grid-cols-12 lg:items-start">"""

content = content.replace(before_return, after_return)

with open("frontend/features/loop/LoopSessionWorkbench.tsx", "w", encoding="utf-8") as f:
    f.write(content)
