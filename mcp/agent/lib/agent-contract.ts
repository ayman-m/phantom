export type AgentWorkflow = {
  id: string;
  title: string;
  prompt: string;
  requiredTools: string[];
  outputs: string[];
};

export const agentContract = {
  apiVersion: 'phantom.agentic/v1alpha1',
  kind: 'AgentRuntimeContract',
  metadata: {
    id: 'phantom-soc-simulation-agent',
    name: 'Phantom Agent',
    version: '1.0.0',
    description:
      'Continuous SOC simulation agent with synthetic telemetry, MCP tools, Caldera orchestration, XSIAM validation, and reporting.',
  },
  capabilities: [
    'synthetic-log-generation',
    'scenario-simulation',
    'caldera-adversary-emulation',
    'xsiam-detection-validation',
    'attack-coverage-reporting',
    'standalone-bundle-import',
  ],
  interfaces: {
    ui: {
      route: '/',
      mountPath: '/agents/phantom-soc-simulation-agent',
    },
    manifest: {
      method: 'GET',
      path: '/api/agent/manifest',
    },
    health: {
      method: 'GET',
      path: '/api/agent/health',
    },
    workflows: {
      method: 'GET',
      path: '/api/agent/workflows',
    },
    mcp: {
      env: 'MCP_URL',
      auth: 'MCP_TOKEN',
      // v1.2: ONE embedded MCP. Tool-providing connectors (caldera,
      // xsiam, xlog) live in the bundle and are loaded by this MCP;
      // their per-instance configs come from setup form input via
      // POST /api/v1/setup, not from per-connector MCP URLs.
      connectorInstances: [
        { id: 'embedded-mcp', urlEnv: 'MCP_URL', tokenEnv: 'MCP_TOKEN', required: true },
      ],
    },
    rest: {
      env: 'XLOG_URL',
      basePath: '/api/v1',
    },
  },
  reports: [
    {
      id: 'coverage-report',
      source: 'phantom-rest',
      path: '/api/v1/coverage-report',
      formats: ['json'],
    },
    {
      id: 'simulation-export',
      source: 'phantom-rest',
      path: '/api/v1/simulations/{simulation_id}/export',
      formats: ['json', 'csv', 'markdown'],
    },
  ],
  lifecycle: {
    standalone: {
      start: 'scripts/agent_lifecycle.sh start',
      stop: 'scripts/agent_lifecycle.sh stop',
      restart: 'scripts/agent_lifecycle.sh restart',
      status: 'scripts/agent_lifecycle.sh status',
      health: 'scripts/agent_lifecycle.sh health',
      export: 'scripts/agent_lifecycle.sh export',
    },
    bundle: {
      exportScript: 'scripts/export_agent_bundle.sh',
      importScript: 'scripts/import_agent_bundle.sh',
      signature: 'optional-hmac-sha256',
      secretBinding: 'provider-references',
    },
  },
} as const;

export const agentWorkflows: AgentWorkflow[] = [
  {
    id: 'generate-logs',
    title: 'Generate logs',
    prompt:
      'Generate JSON firewall logs for Fortinet. First load matching simulation skills, then call data_sources_installed_as_vendors and phantom_get_field_info before creating the worker.',
    requiredTools: ['data_sources_installed_as_vendors', 'phantom_get_field_info', 'phantom_create_data_worker'],
    outputs: ['worker_ids', 'simulation_id', 'log_destination'],
  },
  {
    id: 'run-scenario',
    title: 'Run scenario',
    prompt:
      'Run a scenario for internal reconnaissance against 10.10.20.5, create the workers, then return the simulation ID and worker IDs.',
    requiredTools: ['load_simulation_skills', 'phantom_create_scenario_worker', 'phantom_get_simulation_result'],
    outputs: ['simulation_id', 'worker_ids', 'scenario_summary'],
  },
  {
    id: 'validate-detection',
    title: 'Validate detection',
    prompt:
      'Validate detection coverage for simulation ID <paste simulation ID>. Run the relevant XSIAM query, then call phantom_run_detection_validation with the observed result.',
    requiredTools: ['xsiam_run_xql_query', 'phantom_run_detection_validation', 'phantom_get_simulation_result'],
    outputs: ['validation_result', 'missed_detections', 'recommended_rules'],
  },
  {
    id: 'create-caldera-operation',
    title: 'Create Caldera operation',
    prompt:
      'Create a Caldera adversary and operation, map ability IDs to ATT&CK techniques, then plan matching Phantom defensive telemetry for the operation timeline.',
    requiredTools: ['caldera_create_adversary', 'caldera_create_operation', 'caldera_get_operation_event_logs'],
    outputs: ['caldera_operation_id', 'attack_timeline', 'defensive_telemetry_plan'],
  },
  {
    id: 'review-soc-coverage',
    title: 'Review SOC coverage',
    prompt:
      'Generate a SOC coverage report with phantom_generate_coverage_report and summarize ATT&CK coverage, missed detections, noisy fields, log source gaps, and recommended rules.',
    requiredTools: ['phantom_generate_coverage_report'],
    outputs: ['attack_coverage', 'missed_detections', 'log_source_gaps', 'recommended_rules'],
  },
];
