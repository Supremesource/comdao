# Module Curation Dao

This bot is designed to manage the nomination and removal of modules from a whitelist using a multisignature address stored as a global parameter. The bot interacts with users through Discord commands. For better understanding please refer to the following issue [initial-issue](https://github.com/agicommies/subspace-network/issues/40)

## Decentralization Concerns

Arguably, the bot is a single point of failure, where only one person holds all of the multisignature keys. However, the public address of the multisignature account is being stored as a global on-chain parameter. This means that if the person running the bot becomes unavailable, acts dishonestly, or is otherwise unable to continue running the bot, the governance process can vote to change the global parameter to a new multisignature address. This would effectively allow the community to replace the bot with a new instance, as the bot is fully open source and can be run by anyone.

## Discord Commands

### General Commands

- `/apply`: Allows anyone to apply for module whitelisting by providing the following information:
  - SS58 address of the module
  - Description of what the module does
  - Module endpoint information
  - Team members (developers of the module)
  - GitHub, GitLab, or any other repository link (code must be open source)

  After the command is executed, the bot displays a nicely formatted message, and the SS58 address of the module serves as the request ID.

### Module Nominator Commands

Users with the "module_nominator" role in the Discord server have access to the following commands:

- [x] `/approve <ss58_key>`: Approves ticket for a module.
- [x] `/remove <ss58_key> <reason>`: Starts a ticket for removing a module from the whitelist.
- [x] `/reject <ss58_key> <reason>`: Rejects a ticket for a module.
- [x] `/stats`: Lists a table of members and their `multisig_participation_count` and `multisig_abscence_count`, ranked by participation.
- [x] `/help`: Posts an informational message.

## Contributing

Contributions to this project are welcome. Please submit a pull request or open an issue on the GitHub repository.
