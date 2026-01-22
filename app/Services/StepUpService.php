<?php

namespace App\Services;

use App\Models\User;
use App\Models\AuditLog;
use Illuminate\Support\Facades\Hash;
use Illuminate\Support\Facades\Redis;
use Illuminate\Support\Str;

/**
 * StepUpService - Autenticação de Segundo Fator para Ações Críticas
 * 
 * Gerencia tokens temporários que autorizam ações sensíveis como assinatura de documentos.
 * 
 * Fluxo:
 * 1. Usuário quer assinar documento
 * 2. Frontend pede step-up (usuário digita senha PlattArgus)
 * 3. Backend valida e gera grant temporário (90s)
 * 4. Ação de assinatura verifica se grant existe
 * 5. Grant é deletado após uso (single-use)
 */
class StepUpService
{
    private const PREFIX = 'step_up';
    
    private int $ttl;
    private int $maxAttempts;
    private int $lockoutMinutes;

    public function __construct()
    {
        $this->ttl = (int) config('services.step_up.ttl', 90);
        $this->maxAttempts = (int) config('services.step_up.max_attempts', 5);
        $this->lockoutMinutes = (int) config('services.step_up.lockout_minutes', 15);
    }

    /**
     * Solicita um grant de step-up.
     * 
     * @param User $user Usuário solicitante
     * @param string $password Senha do PlattArgus
     * @param string $action Ação a ser autorizada (ex: 'sign', 'sign_block')
     * @param string $targetId ID do alvo (ex: NUP, SEI número)
     * @param string|null $ip IP do cliente
     * @return array ['success' => bool, 'message' => string, 'expires_in' => int|null]
     */
    public function requestGrant(
        User $user, 
        string $password, 
        string $action, 
        string $targetId,
        ?string $ip = null
    ): array {
        // Verifica lockout
        if ($this->isLockedOut($user->id)) {
            $this->logAttempt($user, $action, $targetId, 'locked_out', $ip);
            
            return [
                'success' => false,
                'message' => 'Muitas tentativas. Aguarde alguns minutos.',
                'locked_until' => $this->getLockoutExpiry($user->id),
            ];
        }

        // Valida senha
        if (!Hash::check($password, $user->password)) {
            $this->incrementAttempts($user->id);
            $this->logAttempt($user, $action, $targetId, 'invalid_password', $ip);
            
            $remaining = $this->maxAttempts - $this->getAttempts($user->id);
            
            return [
                'success' => false,
                'message' => "Senha incorreta. {$remaining} tentativa(s) restante(s).",
                'attempts_remaining' => $remaining,
            ];
        }

        // Reseta tentativas após sucesso
        $this->resetAttempts($user->id);

        // Gera grant
        $grantKey = $this->buildKey($user->id, $action, $targetId);
        $grantData = [
            'user_id' => $user->id,
            'action' => $action,
            'target_id' => $targetId,
            'granted_at' => now()->timestamp,
            'expires_at' => now()->addSeconds($this->ttl)->timestamp,
            'ip' => $ip,
            'grant_id' => Str::uuid()->toString(),
        ];

        Redis::setex($grantKey, $this->ttl, json_encode($grantData));
        
        $this->logAttempt($user, $action, $targetId, 'granted', $ip, $grantData);

        return [
            'success' => true,
            'message' => 'Ação autorizada.',
            'expires_in' => $this->ttl,
            'grant_id' => $grantData['grant_id'],
        ];
    }

    /**
     * Verifica se existe um grant válido para a ação.
     * 
     * @param User $user
     * @param string $action
     * @param string $targetId
     * @param string|null $ip IP atual (opcional, para validação extra)
     * @return bool
     */
    public function hasValidGrant(User $user, string $action, string $targetId, ?string $ip = null): bool
    {
        $grantKey = $this->buildKey($user->id, $action, $targetId);
        $grantJson = Redis::get($grantKey);
        
        if (!$grantJson) {
            return false;
        }

        $grant = json_decode($grantJson, true);
        
        // Valida expiração
        if ($grant['expires_at'] < now()->timestamp) {
            Redis::del($grantKey);
            return false;
        }

        // Validação de IP (opcional mas recomendado)
        if ($ip && isset($grant['ip']) && $grant['ip'] !== $ip) {
            // IP mudou - possível sequestro de sessão
            // Você pode optar por invalidar ou apenas logar
            // Por segurança, vamos invalidar:
            // Redis::del($grantKey);
            // return false;
            
            // Ou apenas logar (menos restritivo):
            \Log::warning('Step-up IP mismatch', [
                'user_id' => $user->id,
                'original_ip' => $grant['ip'],
                'current_ip' => $ip,
            ]);
        }

        return true;
    }

    /**
     * Consome o grant (uso único).
     * Deve ser chamado APÓS executar a ação com sucesso.
     * 
     * @param User $user
     * @param string $action
     * @param string $targetId
     * @return bool Se havia grant para consumir
     */
    public function consumeGrant(User $user, string $action, string $targetId): bool
    {
        $grantKey = $this->buildKey($user->id, $action, $targetId);
        return Redis::del($grantKey) > 0;
    }

    /**
     * Invalida todos os grants de um usuário.
     * Útil para logout forçado ou comprometimento de conta.
     * 
     * @param int $userId
     * @return int Número de grants invalidados
     */
    public function invalidateAllGrants(int $userId): int
    {
        $pattern = self::PREFIX . ":{$userId}:*";
        $keys = Redis::keys($pattern);
        
        if (empty($keys)) {
            return 0;
        }

        return Redis::del(...$keys);
    }

    /**
     * Lista grants ativos de um usuário (para debug/admin).
     * 
     * @param int $userId
     * @return array
     */
    public function getActiveGrants(int $userId): array
    {
        $pattern = self::PREFIX . ":{$userId}:*";
        $keys = Redis::keys($pattern);
        
        $grants = [];
        foreach ($keys as $key) {
            $data = Redis::get($key);
            if ($data) {
                $grants[] = json_decode($data, true);
            }
        }

        return $grants;
    }

    // =========================================================================
    // RATE LIMITING / LOCKOUT
    // =========================================================================

    private function getAttemptsKey(int $userId): string
    {
        return "step_up_attempts:{$userId}";
    }

    private function getLockoutKey(int $userId): string
    {
        return "step_up_lockout:{$userId}";
    }

    private function getAttempts(int $userId): int
    {
        return (int) Redis::get($this->getAttemptsKey($userId));
    }

    private function incrementAttempts(int $userId): void
    {
        $key = $this->getAttemptsKey($userId);
        Redis::incr($key);
        Redis::expire($key, 3600); // Expira em 1 hora

        // Se excedeu, aplica lockout
        if ($this->getAttempts($userId) >= $this->maxAttempts) {
            $this->applyLockout($userId);
        }
    }

    private function resetAttempts(int $userId): void
    {
        Redis::del($this->getAttemptsKey($userId));
    }

    private function applyLockout(int $userId): void
    {
        $key = $this->getLockoutKey($userId);
        $expiry = now()->addMinutes($this->lockoutMinutes)->timestamp;
        Redis::setex($key, $this->lockoutMinutes * 60, $expiry);
    }

    private function isLockedOut(int $userId): bool
    {
        return Redis::exists($this->getLockoutKey($userId));
    }

    private function getLockoutExpiry(int $userId): ?int
    {
        $expiry = Redis::get($this->getLockoutKey($userId));
        return $expiry ? (int) $expiry : null;
    }

    // =========================================================================
    // HELPERS
    // =========================================================================

    private function buildKey(int $userId, string $action, string $targetId): string
    {
        // Sanitiza targetId para evitar problemas com caracteres especiais
        $safeTarget = preg_replace('/[^a-zA-Z0-9_\-.]/', '_', $targetId);
        return self::PREFIX . ":{$userId}:{$action}:{$safeTarget}";
    }

    private function logAttempt(
        User $user, 
        string $action, 
        string $targetId, 
        string $status, 
        ?string $ip,
        array $extra = []
    ): void {
        AuditLog::create([
            'user_id' => $user->id,
            'action' => 'step_up_' . $status,
            'target_type' => 'step_up',
            'target_id' => $targetId,
            'status' => $status === 'granted' ? 'success' : 'failure',
            'ip_address' => $ip,
            'metadata' => array_merge([
                'requested_action' => $action,
            ], $extra),
        ]);
    }
}
