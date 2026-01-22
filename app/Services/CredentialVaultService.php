<?php

namespace App\Services;

use RuntimeException;

/**
 * CredentialVaultService - Cofre de Credenciais SEI
 * 
 * Criptografia AES-256-GCM para armazenamento seguro de senhas do SEI.
 * 
 * Uso:
 *   $vault = app(CredentialVaultService::class);
 *   
 *   // Criptografar
 *   $encrypted = $vault->encrypt('senha_sei');
 *   // Retorna: ['ciphertext' => '...', 'iv' => '...', 'tag' => '...']
 *   
 *   // Descriptografar
 *   $senha = $vault->decrypt($ciphertext, $iv, $tag);
 */
class CredentialVaultService
{
    private const CIPHER = 'aes-256-gcm';
    private const IV_LENGTH = 12;  // 96 bits para GCM
    private const TAG_LENGTH = 16; // 128 bits
    
    private string $masterKey;

    public function __construct()
    {
        $keyHex = config('services.argus.master_key');
        
        if (empty($keyHex)) {
            throw new RuntimeException(
                'ARGUS_MASTER_KEY não configurada. ' .
                'Gere uma chave com: php artisan plattargus:generate-master-key'
            );
        }

        $this->masterKey = hex2bin($keyHex);
        
        if (strlen($this->masterKey) !== 32) {
            throw new RuntimeException(
                'ARGUS_MASTER_KEY deve ter 64 caracteres hexadecimais (32 bytes). ' .
                'Atual: ' . strlen($keyHex) . ' caracteres.'
            );
        }
    }

    /**
     * Criptografa uma senha usando AES-256-GCM.
     * 
     * @param string $plaintext Senha em texto plano
     * @return array ['ciphertext' => string, 'iv' => string, 'tag' => string]
     * @throws RuntimeException Se a criptografia falhar
     */
    public function encrypt(string $plaintext): array
    {
        // Gera IV aleatório
        $iv = random_bytes(self::IV_LENGTH);
        
        // Criptografa
        $ciphertext = openssl_encrypt(
            $plaintext,
            self::CIPHER,
            $this->masterKey,
            OPENSSL_RAW_DATA,
            $iv,
            $tag,
            '',
            self::TAG_LENGTH
        );
        
        if ($ciphertext === false) {
            throw new RuntimeException('Falha na criptografia: ' . openssl_error_string());
        }
        
        return [
            'ciphertext' => base64_encode($ciphertext),
            'iv' => base64_encode($iv),
            'tag' => base64_encode($tag),
        ];
    }

    /**
     * Descriptografa uma senha.
     * 
     * @param string $ciphertext Texto cifrado (base64)
     * @param string $iv Vetor de inicialização (base64)
     * @param string $tag Tag de autenticação (base64)
     * @return string Senha em texto plano
     * @throws RuntimeException Se a descriptografia falhar
     */
    public function decrypt(string $ciphertext, string $iv, string $tag): string
    {
        $ciphertextRaw = base64_decode($ciphertext, true);
        $ivRaw = base64_decode($iv, true);
        $tagRaw = base64_decode($tag, true);
        
        if ($ciphertextRaw === false || $ivRaw === false || $tagRaw === false) {
            throw new RuntimeException('Dados criptografados inválidos (base64 malformado)');
        }
        
        $plaintext = openssl_decrypt(
            $ciphertextRaw,
            self::CIPHER,
            $this->masterKey,
            OPENSSL_RAW_DATA,
            $ivRaw,
            $tagRaw
        );
        
        if ($plaintext === false) {
            throw new RuntimeException(
                'Falha na descriptografia. Possíveis causas: ' .
                'chave incorreta, dados corrompidos ou adulterados.'
            );
        }
        
        return $plaintext;
    }

    /**
     * Verifica se uma credencial criptografada é válida.
     * 
     * @param string|null $ciphertext
     * @param string|null $iv
     * @param string|null $tag
     * @return bool
     */
    public function isValid(?string $ciphertext, ?string $iv, ?string $tag): bool
    {
        if (empty($ciphertext) || empty($iv) || empty($tag)) {
            return false;
        }
        
        try {
            $this->decrypt($ciphertext, $iv, $tag);
            return true;
        } catch (\Exception $e) {
            return false;
        }
    }

    /**
     * Gera uma nova master key.
     * Use apenas para setup inicial ou rotação de chaves.
     * 
     * @return string Chave em formato hexadecimal (64 caracteres)
     */
    public static function generateMasterKey(): string
    {
        return bin2hex(random_bytes(32));
    }

    /**
     * Recriptografa uma credencial com uma nova chave.
     * Útil para rotação de chaves.
     * 
     * @param string $ciphertext Texto cifrado atual
     * @param string $iv IV atual
     * @param string $tag Tag atual
     * @param string $newKeyHex Nova chave em hex
     * @return array Nova credencial criptografada
     */
    public function recrypt(string $ciphertext, string $iv, string $tag, string $newKeyHex): array
    {
        // Descriptografa com chave atual
        $plaintext = $this->decrypt($ciphertext, $iv, $tag);
        
        // Cria novo vault com nova chave
        $newVault = new self();
        
        // Temporariamente usa a nova chave
        $reflection = new \ReflectionClass($newVault);
        $property = $reflection->getProperty('masterKey');
        $property->setAccessible(true);
        $property->setValue($newVault, hex2bin($newKeyHex));
        
        // Recriptografa
        $newEncrypted = $newVault->encrypt($plaintext);
        
        // Limpa plaintext da memória
        $plaintext = str_repeat("\0", strlen($plaintext));
        unset($plaintext);
        
        return $newEncrypted;
    }
}
