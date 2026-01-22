<?php

namespace App\Console\Commands;

use App\Services\CredentialVaultService;
use Illuminate\Console\Command;

class GenerateMasterKey extends Command
{
    /**
     * The name and signature of the console command.
     */
    protected $signature = 'plattargus:generate-master-key 
                            {--show : Apenas mostra a chave sem instruções}';

    /**
     * The console command description.
     */
    protected $description = 'Gera uma nova ARGUS_MASTER_KEY para criptografia de credenciais SEI';

    /**
     * Execute the console command.
     */
    public function handle(): int
    {
        $key = CredentialVaultService::generateMasterKey();

        if ($this->option('show')) {
            $this->line($key);
            return Command::SUCCESS;
        }

        $this->newLine();
        $this->info('═══════════════════════════════════════════════════════════════');
        $this->info('   🔐 NOVA ARGUS_MASTER_KEY GERADA');
        $this->info('═══════════════════════════════════════════════════════════════');
        $this->newLine();
        
        $this->line("   <fg=yellow>{$key}</>");
        
        $this->newLine();
        $this->info('═══════════════════════════════════════════════════════════════');
        $this->newLine();
        
        $this->warn('   ⚠️  INSTRUÇÕES IMPORTANTES:');
        $this->newLine();
        $this->line('   1. Adicione ao seu arquivo .env:');
        $this->line("      <fg=green>ARGUS_MASTER_KEY={$key}</>");
        $this->newLine();
        $this->line('   2. <fg=red>NUNCA</> commite esta chave no Git!');
        $this->newLine();
        $this->line('   3. Faça backup seguro desta chave.');
        $this->line('      Se perdê-la, todas as credenciais SEI serão perdidas.');
        $this->newLine();
        $this->line('   4. Em produção, considere usar:');
        $this->line('      - AWS KMS');
        $this->line('      - HashiCorp Vault');
        $this->line('      - Azure Key Vault');
        $this->newLine();
        $this->info('═══════════════════════════════════════════════════════════════');
        $this->newLine();

        // Pergunta se quer adicionar ao .env automaticamente
        if ($this->confirm('Deseja adicionar automaticamente ao .env?', false)) {
            $envPath = base_path('.env');
            
            if (!file_exists($envPath)) {
                $this->error('.env não encontrado. Crie a partir do .env.example');
                return Command::FAILURE;
            }

            $envContent = file_get_contents($envPath);
            
            if (str_contains($envContent, 'ARGUS_MASTER_KEY=')) {
                // Substitui existente
                $envContent = preg_replace(
                    '/ARGUS_MASTER_KEY=.*/',
                    "ARGUS_MASTER_KEY={$key}",
                    $envContent
                );
            } else {
                // Adiciona no final
                $envContent .= "\nARGUS_MASTER_KEY={$key}\n";
            }

            file_put_contents($envPath, $envContent);
            $this->info('✅ ARGUS_MASTER_KEY adicionada ao .env');
        }

        return Command::SUCCESS;
    }
}
