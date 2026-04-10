while true; do
    sudo env/bin/cynthia
    case $? in
        0)
            break
            ;;
        1)
            break
            ;;
        *)
            ;;
    esac
done
