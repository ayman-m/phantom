const DEFAULT_GATEWAY_URL = "http://api-gateway:8080";

export function resolveGatewayUrl(): string {
  const configuredGatewayUrl = process.env.GATEWAY_URL?.trim();

  if (configuredGatewayUrl) {
    return configuredGatewayUrl;
  }

  return DEFAULT_GATEWAY_URL;
}

